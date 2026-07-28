from app.services.block_storage import load_blocks
from app.services.llm_rewrite import (
    BlockEdit,
    GenerationResult,
    InvalidEditIdsError,
    LLMGenerationError,
)
from tests.docx_fixtures import build_simple_cv

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
JD_TEXT = "Looking for a backend engineer with strong payments experience."


def _session_dir(data_dir, session_id):
    return data_dir / f"session-{session_id}"


def _cv_blocks(data_dir, session_id):
    return load_blocks(_session_dir(data_dir, session_id), "cv_blocks.json")


def _post_jd(client, session_id, text=JD_TEXT):
    response = client.post(f"/sessions/{session_id}/job-description", data={"text": text})
    assert response.status_code == 200


def _editable_cv_block(data_dir, session_id):
    blocks = _cv_blocks(data_dir, session_id)
    return next(b for b in blocks if b.editable)


def _fake_generate(cv_edit_texts=None, cl_edit_texts=None, low_confidence=False, raise_error=None):
    """Returns a stand-in for llm_rewrite.generate_tailored_edits with a
    fixed response, so tests never hit the real Anthropic API."""

    def _fn(job_description, cv_editable_blocks, cover_letter_editable_blocks=None, *, client=None):
        if raise_error is not None:
            raise raise_error
        cv_edits = []
        if cv_edit_texts:
            cv_edits = [
                BlockEdit(id=cv_editable_blocks[0].id, text=cv_edit_texts)
            ]
        cl_edits = None
        if cover_letter_editable_blocks is not None:
            cl_edits = []
            if cl_edit_texts:
                cl_edits = [BlockEdit(id=cover_letter_editable_blocks[0].id, text=cl_edit_texts)]
        return GenerationResult(
            cv_edits=cv_edits,
            cover_letter_edits=cl_edits,
            low_confidence=low_confidence,
            usage={"input_tokens": 10, "output_tokens": 5},
        )

    return _fn


def test_generate_without_job_description_returns_400(client, session_id):
    response = client.post(f"/sessions/{session_id}/generate")
    assert response.status_code == 400


def test_generate_happy_path_cv_only(client, session_id, data_dir, monkeypatch):
    _post_jd(client, session_id)
    monkeypatch.setattr(
        "app.routers.generation.generate_tailored_edits",
        _fake_generate(cv_edit_texts="Backend engineer with deep payments experience."),
    )

    response = client.post(f"/sessions/{session_id}/generate")
    assert response.status_code == 200
    body = response.json()

    assert body["draft_id"] == 1
    assert body["cover_letter_preview"] is None
    assert "cv" in body["ats"]
    assert "cover_letter" not in body["ats"]

    changed = [b for b in body["cv_preview"] if b["changed"]]
    assert len(changed) == 1
    assert changed[0]["tailored_text"] == "Backend engineer with deep payments experience."


def test_generate_with_cover_letter(client, session_id, data_dir, tmp_path, monkeypatch):
    cl_path = build_simple_cv(tmp_path / "cl.docx")
    client.post(
        f"/sessions/{session_id}/cover-letter",
        files={"file": ("cover_letter.docx", cl_path.read_bytes(), DOCX_CONTENT_TYPE)},
    )
    _post_jd(client, session_id)
    monkeypatch.setattr(
        "app.routers.generation.generate_tailored_edits",
        _fake_generate(cv_edit_texts="Edited CV bullet.", cl_edit_texts="Edited CL bullet."),
    )

    response = client.post(f"/sessions/{session_id}/generate")
    assert response.status_code == 200
    body = response.json()

    assert body["cover_letter_preview"] is not None
    assert "cover_letter" in body["ats"]
    changed_cl = [b for b in body["cover_letter_preview"] if b["changed"]]
    assert len(changed_cl) == 1
    assert changed_cl[0]["tailored_text"] == "Edited CL bullet."


def test_retry_creates_independent_draft_and_reinvokes_llm(client, session_id, monkeypatch):
    _post_jd(client, session_id)
    call_count = {"n": 0}

    def counting_fake(job_description, cv_editable_blocks, cover_letter_editable_blocks=None, *, client=None):
        call_count["n"] += 1
        return GenerationResult(cv_edits=[], cover_letter_edits=None, low_confidence=True, usage={})

    monkeypatch.setattr("app.routers.generation.generate_tailored_edits", counting_fake)

    first = client.post(f"/sessions/{session_id}/generate").json()
    second = client.post(f"/sessions/{session_id}/retry").json()

    assert first["draft_id"] != second["draft_id"]
    assert call_count["n"] == 2


def test_accept_uses_reviewed_draft_without_calling_llm_again(client, session_id, data_dir, monkeypatch):
    _post_jd(client, session_id)
    monkeypatch.setattr(
        "app.routers.generation.generate_tailored_edits",
        _fake_generate(cv_edit_texts="Accepted edit text."),
    )
    generate_response = client.post(f"/sessions/{session_id}/generate")
    draft_id = generate_response.json()["draft_id"]

    def fail_if_called(*args, **kwargs):
        raise AssertionError("generate_tailored_edits must not be called during accept")

    monkeypatch.setattr("app.routers.generation.generate_tailored_edits", fail_if_called)

    accept_response = client.post(f"/sessions/{session_id}/accept", params={"draft_id": draft_id})
    assert accept_response.status_code == 200
    assert accept_response.json()["cv_filename"].endswith(".docx")

    output_path = _session_dir(data_dir, session_id) / "output" / accept_response.json()["cv_filename"]
    assert output_path.exists()


def test_accept_without_prior_generate_returns_400(client, session_id):
    response = client.post(f"/sessions/{session_id}/accept")
    assert response.status_code == 400


def test_download_before_accept_returns_404(client, session_id):
    response = client.get(f"/sessions/{session_id}/download/cv")
    assert response.status_code == 404


def test_download_after_accept_returns_file(client, session_id, monkeypatch):
    _post_jd(client, session_id)
    monkeypatch.setattr(
        "app.routers.generation.generate_tailored_edits",
        _fake_generate(cv_edit_texts="Downloadable edit."),
    )
    client.post(f"/sessions/{session_id}/generate")
    client.post(f"/sessions/{session_id}/accept")

    response = client.get(f"/sessions/{session_id}/download/cv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_llm_error_returns_502_and_session_survives_for_retry(client, session_id, monkeypatch):
    _post_jd(client, session_id)
    monkeypatch.setattr(
        "app.routers.generation.generate_tailored_edits",
        _fake_generate(raise_error=LLMGenerationError("simulated upstream failure")),
    )
    failed_response = client.post(f"/sessions/{session_id}/generate")
    assert failed_response.status_code == 502

    monkeypatch.setattr(
        "app.routers.generation.generate_tailored_edits",
        _fake_generate(cv_edit_texts="Recovered after retry."),
    )
    retry_response = client.post(f"/sessions/{session_id}/retry")
    assert retry_response.status_code == 200


def test_invalid_edit_id_from_model_returns_502(client, session_id, monkeypatch):
    _post_jd(client, session_id)
    monkeypatch.setattr(
        "app.routers.generation.generate_tailored_edits",
        _fake_generate(raise_error=InvalidEditIdsError("cv", ["bogus-id"])),
    )
    response = client.post(f"/sessions/{session_id}/generate")
    assert response.status_code == 502
