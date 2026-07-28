from tests.docx_fixtures import build_simple_cv

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _cv_bytes(tmp_path) -> bytes:
    path = build_simple_cv(tmp_path / "source_cv.docx")
    return path.read_bytes()


def test_upload_valid_cv_returns_session_and_blocks(client, data_dir, tmp_path):
    content = _cv_bytes(tmp_path)
    response = client.post(
        "/sessions/cv",
        files={"file": ("my_cv.docx", content, DOCX_CONTENT_TYPE)},
    )

    assert response.status_code == 200
    body = response.json()
    assert "session_id" in body
    assert body["block_count"] > 0

    session_dir = data_dir / f"session-{body['session_id']}"
    assert (session_dir / "cv.docx").exists()
    assert (session_dir / "cv_blocks.json").exists()


def test_upload_pdf_as_cv_rejected(client, data_dir, tmp_path):
    response = client.post(
        "/sessions/cv",
        files={"file": ("my_cv.pdf", b"%PDF-1.4 fake pdf content", "application/pdf")},
    )

    assert response.status_code == 400
    assert "Word (.docx)" in response.json()["detail"]
    assert list(data_dir.iterdir()) == []  # nothing persisted


def test_upload_corrupt_docx_rejected(client, data_dir, tmp_path):
    response = client.post(
        "/sessions/cv",
        files={"file": ("broken.docx", b"this is not a real docx file", DOCX_CONTENT_TYPE)},
    )

    assert response.status_code == 400
    assert "valid" in response.json()["detail"].lower()
    assert list(data_dir.iterdir()) == []  # session cleaned up, nothing left behind


def test_upload_oversized_file_rejected(client, data_dir, tmp_path):
    oversized = b"0" * (10 * 1024 * 1024 + 1)
    response = client.post(
        "/sessions/cv",
        files={"file": ("big.docx", oversized, DOCX_CONTENT_TYPE)},
    )

    assert response.status_code == 400
    assert "too large" in response.json()["detail"].lower()
    assert list(data_dir.iterdir()) == []


def test_cover_letter_upload_is_optional(client, data_dir, tmp_path):
    content = _cv_bytes(tmp_path)
    response = client.post(
        "/sessions/cv",
        files={"file": ("my_cv.docx", content, DOCX_CONTENT_TYPE)},
    )
    session_id = response.json()["session_id"]
    session_dir = data_dir / f"session-{session_id}"

    assert (session_dir / "cv_blocks.json").exists()
    assert not (session_dir / "cover_letter_blocks.json").exists()


def test_cover_letter_upload_attaches_to_existing_session(client, data_dir, tmp_path):
    cv_response = client.post(
        "/sessions/cv",
        files={"file": ("my_cv.docx", _cv_bytes(tmp_path), DOCX_CONTENT_TYPE)},
    )
    session_id = cv_response.json()["session_id"]

    cl_content = _cv_bytes(tmp_path)  # any valid docx works as a cover letter fixture too
    cl_response = client.post(
        f"/sessions/{session_id}/cover-letter",
        files={"file": ("cover_letter.docx", cl_content, DOCX_CONTENT_TYPE)},
    )

    assert cl_response.status_code == 200
    assert cl_response.json()["session_id"] == session_id

    session_dir = data_dir / f"session-{session_id}"
    assert (session_dir / "cover_letter.docx").exists()
    assert (session_dir / "cover_letter_blocks.json").exists()


def test_cover_letter_upload_to_missing_session_404(client, tmp_path):
    response = client.post(
        "/sessions/does-not-exist/cover-letter",
        files={"file": ("cover_letter.docx", _cv_bytes(tmp_path), DOCX_CONTENT_TYPE)},
    )
    assert response.status_code == 404
