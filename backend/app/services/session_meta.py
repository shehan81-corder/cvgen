import json
from pathlib import Path

METADATA_FILENAME = "meta.json"


def _load(session_dir: Path) -> dict:
    path = session_dir / METADATA_FILENAME
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save(session_dir: Path, data: dict) -> None:
    (session_dir / METADATA_FILENAME).write_text(json.dumps(data, indent=2))


def set_original_filename(session_dir: Path, document: str, filename: str) -> None:
    data = _load(session_dir)
    data.setdefault("original_filenames", {})[document] = filename
    _save(session_dir, data)


def get_original_filename(session_dir: Path, document: str) -> str | None:
    data = _load(session_dir)
    return data.get("original_filenames", {}).get(document)


def set_output_filename(session_dir: Path, document: str, filename: str) -> None:
    data = _load(session_dir)
    data.setdefault("output_filenames", {})[document] = filename
    _save(session_dir, data)


def get_output_filename(session_dir: Path, document: str) -> str | None:
    data = _load(session_dir)
    return data.get("output_filenames", {}).get(document)
