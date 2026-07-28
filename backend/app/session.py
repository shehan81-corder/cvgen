import os
import uuid
from pathlib import Path

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _data_dir() -> Path:
    # Overridable so tests can point sessions at an isolated tmp directory
    # instead of the real ./data working directory.
    override = os.environ.get("CVGEN_DATA_DIR")
    return Path(override) if override else _DEFAULT_DATA_DIR


def create_session_dir() -> Path:
    session_dir = _data_dir() / f"session-{uuid.uuid4()}"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def get_session_dir(session_id: str) -> Path | None:
    session_dir = _data_dir() / f"session-{session_id}"
    return session_dir if session_dir.is_dir() else None
