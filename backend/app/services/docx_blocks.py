"""Extract text runs from a .docx as a flat list of stably-identified "blocks".

See architecture.md §3 for the block model this implements.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from pydantic import BaseModel


class BlockLocation(BaseModel):
    kind: Literal["paragraph", "table_cell"]
    paragraph_index: int
    run_index: int
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None


class RunStyle(BaseModel):
    font: str | None = None
    size: float | None = None
    color: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None


class Block(BaseModel):
    id: str
    text: str
    style_name: str | None = None
    location: BlockLocation
    run_style: RunStyle
    # Filled in later by the classifier (see app/services/classifier.py).
    section: str | None = None
    editable: bool | None = None


def _run_style(run: Run) -> RunStyle:
    color: str | None = None
    try:
        rgb = run.font.color.rgb if run.font.color is not None else None
        if rgb is not None:
            color = f"#{rgb}"
    except AttributeError:
        color = None

    size = run.font.size.pt if run.font.size is not None else None
    underline = None if run.underline is None else bool(run.underline)

    return RunStyle(
        font=run.font.name,
        size=size,
        color=color,
        bold=run.bold,
        italic=run.italic,
        underline=underline,
    )


def _paragraph_blocks(
    paragraph: Paragraph,
    paragraph_index: int,
    *,
    table_index: int | None = None,
    row_index: int | None = None,
    cell_index: int | None = None,
) -> list[Block]:
    style_name = paragraph.style.name if paragraph.style is not None else None
    kind: Literal["paragraph", "table_cell"] = "paragraph" if table_index is None else "table_cell"

    blocks: list[Block] = []
    for run_index, run in enumerate(paragraph.runs):
        if not run.text:
            continue

        if table_index is None:
            block_id = f"p{paragraph_index}-r{run_index}"
        else:
            block_id = f"t{table_index}-row{row_index}-c{cell_index}-p{paragraph_index}-r{run_index}"

        blocks.append(
            Block(
                id=block_id,
                text=run.text,
                style_name=style_name,
                location=BlockLocation(
                    kind=kind,
                    paragraph_index=paragraph_index,
                    run_index=run_index,
                    table_index=table_index,
                    row_index=row_index,
                    cell_index=cell_index,
                ),
                run_style=_run_style(run),
            )
        )
    return blocks


def _table_blocks(table: Table, table_index: int) -> list[Block]:
    blocks: list[Block] = []
    for row_index, row in enumerate(table.rows):
        for cell_index, cell in enumerate(row.cells):
            for paragraph_index, paragraph in enumerate(cell.paragraphs):
                blocks.extend(
                    _paragraph_blocks(
                        paragraph,
                        paragraph_index,
                        table_index=table_index,
                        row_index=row_index,
                        cell_index=cell_index,
                    )
                )
    return blocks


def extract_blocks(path: str | Path) -> list[Block]:
    """Walk a .docx in true document order and return every visible text run as a Block.

    Body paragraphs and tables are visited via `iter_inner_content()` so
    interleaving is preserved (needed for the classifier's section-tracking
    in app/services/classifier.py). Nested tables inside table cells are not
    walked (rare in CVs; documented limitation).
    """
    document = Document(str(path))
    blocks: list[Block] = []
    paragraph_index = 0
    table_index = 0

    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            blocks.extend(_paragraph_blocks(item, paragraph_index))
            paragraph_index += 1
        elif isinstance(item, Table):
            blocks.extend(_table_blocks(item, table_index))
            table_index += 1

    return blocks


def blocks_text(blocks: list[Block]) -> str:
    return " ".join(b.text for b in blocks)
