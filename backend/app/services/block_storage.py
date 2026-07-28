import json
from pathlib import Path

from app.services.docx_blocks import Block


def save_blocks(session_dir: Path, filename: str, blocks: list[Block]) -> None:
    data = [b.model_dump() for b in blocks]
    (session_dir / filename).write_text(json.dumps(data, indent=2))


def load_blocks(session_dir: Path, filename: str) -> list[Block]:
    data = json.loads((session_dir / filename).read_text())
    return [Block.model_validate(b) for b in data]
