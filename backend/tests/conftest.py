import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.docx_fixtures import build_simple_cv

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CVGEN_DATA_DIR", str(tmp_path))
    return TestClient(app)


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path


@pytest.fixture
def session_id(client, tmp_path):
    path = build_simple_cv(tmp_path / "session_cv.docx")
    response = client.post(
        "/sessions/cv",
        files={"file": ("cv.docx", path.read_bytes(), DOCX_CONTENT_TYPE)},
    )
    return response.json()["session_id"]
