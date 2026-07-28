from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services.ats_scoring import match_score
from app.services.block_storage import load_blocks
from app.services.docx_blocks import blocks_text
from app.services.docx_writer import (
    apply_edits_to_docx,
    build_preview,
    make_output_filename,
    tailored_text,
)
from app.services.draft_storage import draft_ids, load_draft, save_draft
from app.services.job_description import load_job_description
from app.services.llm_rewrite import (
    BlockEdit,
    InvalidEditIdsError,
    LLMGenerationError,
    generate_tailored_edits,
)
from app.services.session_meta import (
    get_original_filename,
    get_output_filename,
    set_output_filename,
)
from app.session import get_session_dir

router = APIRouter(prefix="/sessions", tags=["generation"])

_DOWNLOAD_KEYS = {"cv": "cv", "cover-letter": "cover_letter"}


def _require_session(session_id: str) -> Path:
    session_dir = get_session_dir(session_id)
    if session_dir is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session_dir


def _load_cv_blocks(session_dir: Path):
    if not (session_dir / "cv_blocks.json").exists():
        raise HTTPException(status_code=400, detail="No CV uploaded for this session.")
    return load_blocks(session_dir, "cv_blocks.json")


def _load_cover_letter_blocks(session_dir: Path):
    if not (session_dir / "cover_letter_blocks.json").exists():
        return None
    return load_blocks(session_dir, "cover_letter_blocks.json")


def _run_generation(session_dir: Path, session_id: str) -> dict:
    jd_text = load_job_description(session_dir)
    if not jd_text:
        raise HTTPException(
            status_code=400, detail="Job description is required before generating."
        )

    cv_blocks = _load_cv_blocks(session_dir)
    cl_blocks = _load_cover_letter_blocks(session_dir)

    cv_editable = [b for b in cv_blocks if b.editable]
    cl_editable = [b for b in cl_blocks if b.editable] if cl_blocks is not None else None

    try:
        result = generate_tailored_edits(jd_text, cv_editable, cl_editable)
    except InvalidEditIdsError as exc:
        raise HTTPException(
            status_code=502, detail=f"Model returned an out-of-scope edit: {exc}"
        ) from exc
    except LLMGenerationError as exc:
        raise HTTPException(status_code=502, detail=f"Generation failed: {exc}") from exc
    except Exception as exc:  # network/API errors from the Anthropic client
        raise HTTPException(
            status_code=502,
            detail="Generation failed due to an upstream error. You can retry.",
        ) from exc

    ats = {
        "cv": {
            "original": match_score(jd_text, blocks_text(cv_blocks)),
            "tailored": match_score(jd_text, tailored_text(cv_blocks, result.cv_edits)),
        }
    }
    cl_preview = None
    cl_edits_for_draft = None
    if cl_blocks is not None:
        cl_edits = result.cover_letter_edits or []
        cl_edits_for_draft = cl_edits
        ats["cover_letter"] = {
            "original": match_score(jd_text, blocks_text(cl_blocks)),
            "tailored": match_score(jd_text, tailored_text(cl_blocks, cl_edits)),
        }
        cl_preview = build_preview(cl_blocks, cl_edits)

    draft_id = (max(draft_ids(session_dir), default=0)) + 1
    save_draft(
        session_dir,
        draft_id,
        {
            "cv_edits": [e.__dict__ for e in result.cv_edits],
            "cover_letter_edits": (
                [e.__dict__ for e in cl_edits_for_draft] if cl_edits_for_draft is not None else None
            ),
            "low_confidence": result.low_confidence,
            "ats": ats,
        },
    )

    return {
        "session_id": session_id,
        "draft_id": draft_id,
        "low_confidence": result.low_confidence,
        "ats": ats,
        "cv_preview": build_preview(cv_blocks, result.cv_edits),
        "cover_letter_preview": cl_preview,
    }


@router.post("/{session_id}/generate")
def generate(session_id: str):
    session_dir = _require_session(session_id)
    return _run_generation(session_dir, session_id)


@router.post("/{session_id}/retry")
def retry(session_id: str):
    session_dir = _require_session(session_id)
    return _run_generation(session_dir, session_id)


@router.post("/{session_id}/accept")
def accept(session_id: str, draft_id: int | None = None):
    session_dir = _require_session(session_id)

    ids = draft_ids(session_dir)
    if not ids:
        raise HTTPException(status_code=400, detail="No draft to accept. Generate first.")
    target_draft_id = draft_id if draft_id is not None else max(ids)
    if target_draft_id not in ids:
        raise HTTPException(status_code=404, detail=f"Draft {target_draft_id} not found.")

    draft = load_draft(session_dir, target_draft_id)
    jd_text = load_job_description(session_dir) or ""

    cv_blocks = _load_cv_blocks(session_dir)
    cv_edits = [BlockEdit(**e) for e in draft["cv_edits"]]
    cv_original_filename = get_original_filename(session_dir, "cv") or "cv.docx"
    cv_output_name = make_output_filename(cv_original_filename, jd_text)
    apply_edits_to_docx(
        session_dir / "cv.docx", cv_blocks, cv_edits, session_dir / "output" / cv_output_name
    )
    set_output_filename(session_dir, "cv", cv_output_name)

    response = {"session_id": session_id, "draft_id": target_draft_id, "cv_filename": cv_output_name}

    cl_blocks = _load_cover_letter_blocks(session_dir)
    if cl_blocks is not None and draft.get("cover_letter_edits") is not None:
        cl_edits = [BlockEdit(**e) for e in draft["cover_letter_edits"]]
        cl_original_filename = get_original_filename(session_dir, "cover_letter") or "cover_letter.docx"
        cl_output_name = make_output_filename(cl_original_filename, jd_text)
        apply_edits_to_docx(
            session_dir / "cover_letter.docx",
            cl_blocks,
            cl_edits,
            session_dir / "output" / cl_output_name,
        )
        set_output_filename(session_dir, "cover_letter", cl_output_name)
        response["cover_letter_filename"] = cl_output_name

    return response


@router.get("/{session_id}/download/{document}")
def download(session_id: str, document: str):
    if document not in _DOWNLOAD_KEYS:
        raise HTTPException(status_code=404, detail="Unknown document type.")
    session_dir = _require_session(session_id)

    key = _DOWNLOAD_KEYS[document]
    filename = get_output_filename(session_dir, key)
    if filename is None:
        raise HTTPException(
            status_code=404, detail="No accepted output yet for this document. Call accept first."
        )

    path = session_dir / "output" / filename
    return FileResponse(
        path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
