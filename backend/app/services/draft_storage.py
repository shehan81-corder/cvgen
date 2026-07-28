import json
import re
from pathlib import Path

_DRAFT_PATTERN = re.compile(r"draft_(\d+)\.json$")


def draft_ids(session_dir: Path) -> list[int]:
    ids = []
    for f in session_dir.glob("draft_*.json"):
        match = _DRAFT_PATTERN.search(f.name)
        if match:
            ids.append(int(match.group(1)))
    return sorted(ids)


def save_draft(session_dir: Path, draft_id: int, data: dict) -> None:
    (session_dir / f"draft_{draft_id}.json").write_text(json.dumps(data, indent=2))


def load_draft(session_dir: Path, draft_id: int) -> dict:
    path = session_dir / f"draft_{draft_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Draft {draft_id} not found")
    return json.loads(path.read_text())
