import shutil

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services.block_storage import save_blocks
from app.services.classifier import classify_blocks
from app.services.docx_blocks import extract_blocks
from app.services.job_description import (
    extract_text_from_docx,
    extract_text_from_pdf,
    load_job_description,
    save_job_description,
)
from app.services.session_meta import set_original_filename
from app.session import create_session_dir, get_session_dir

router = APIRouter(prefix="/sessions", tags=["sessions"])

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


def _validate_docx_filename(filename: str | None, field: str) -> None:
    if not filename or not filename.lower().endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Please upload the Word (.docx) version of your {field} "
                "— PDF can't preserve exact formatting."
            ),
        )


def _validate_size(content: bytes) -> None:
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File is too large (max 10 MB).")


def _parse_error(field: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail=(
            f"Could not read the uploaded {field}. Make sure it's a valid, "
            "non-password-protected Word document."
        ),
    )


def _require_session(session_id: str):
    session_dir = get_session_dir(session_id)
    if session_dir is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session_dir


@router.post("/cv")
async def upload_cv(file: UploadFile = File(...)):
    _validate_docx_filename(file.filename, "CV")
    content = await file.read()
    _validate_size(content)

    session_dir = create_session_dir()
    cv_path = session_dir / "cv.docx"
    cv_path.write_bytes(content)

    try:
        blocks = extract_blocks(cv_path)
    except Exception as exc:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise _parse_error("CV") from exc

    classified = classify_blocks(blocks)
    save_blocks(session_dir, "cv_blocks.json", classified)
    set_original_filename(session_dir, "cv", file.filename)

    session_id = session_dir.name.removeprefix("session-")
    return {"session_id": session_id, "block_count": len(classified)}


@router.post("/{session_id}/cover-letter")
async def upload_cover_letter(session_id: str, file: UploadFile = File(...)):
    session_dir = _require_session(session_id)

    _validate_docx_filename(file.filename, "cover letter")
    content = await file.read()
    _validate_size(content)

    cl_path = session_dir / "cover_letter.docx"
    cl_path.write_bytes(content)

    try:
        blocks = extract_blocks(cl_path)
    except Exception as exc:
        cl_path.unlink(missing_ok=True)
        raise _parse_error("cover letter") from exc

    classified = classify_blocks(blocks, document_type="cover_letter")
    save_blocks(session_dir, "cover_letter_blocks.json", classified)
    set_original_filename(session_dir, "cover_letter", file.filename)

    return {"session_id": session_id, "block_count": len(classified)}


@router.post("/{session_id}/job-description")
async def upload_job_description(
    session_id: str,
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
):
    session_dir = _require_session(session_id)

    has_text = text is not None and text.strip()
    if file is not None and has_text:
        raise HTTPException(
            status_code=400, detail="Provide either pasted text or a file, not both."
        )

    if file is not None:
        filename = (file.filename or "").lower()
        if not (filename.endswith(".docx") or filename.endswith(".pdf")):
            raise HTTPException(
                status_code=400, detail="Job description file must be a .docx or .pdf."
            )
        content = await file.read()
        _validate_size(content)
        try:
            jd_text = (
                extract_text_from_docx(content)
                if filename.endswith(".docx")
                else extract_text_from_pdf(content)
            )
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail="Could not read the uploaded job description file.",
            ) from exc
    elif has_text:
        jd_text = text
    else:
        raise HTTPException(
            status_code=400, detail="Job description text or file is required."
        )

    if not jd_text.strip():
        raise HTTPException(
            status_code=400, detail="No readable text found in the job description."
        )

    save_job_description(session_dir, jd_text)
    return {"session_id": session_id, "character_count": len(jd_text)}


@router.get("/{session_id}/job-description")
def get_job_description(session_id: str):
    session_dir = _require_session(session_id)
    jd_text = load_job_description(session_dir)
    if jd_text is None:
        raise HTTPException(
            status_code=404, detail="No job description uploaded for this session."
        )
    return {"session_id": session_id, "text": jd_text}
