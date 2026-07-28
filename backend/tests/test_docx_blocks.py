from app.services.docx_blocks import extract_blocks
from tests.docx_fixtures import build_simple_cv


def test_extracts_every_visible_text_run(tmp_path):
    path = build_simple_cv(tmp_path / "cv.docx")
    blocks = extract_blocks(path)
    texts = {b.text for b in blocks}

    assert "JOHN SMITH" in texts
    assert "john.smith@example.com | +1 555-123-4567" in texts
    assert "Summary" in texts
    assert "Backend engineer with 8 years building payment systems." in texts
    assert "Experience" in texts
    assert "Senior Engineer, Acme Corp" in texts
    assert "Jan 2020 - Present" in texts
    assert "Led migration of the billing service to a new provider." in texts
    assert "Python" in texts
    assert "PostgreSQL" in texts


def test_block_ids_are_stable_across_repeated_calls(tmp_path):
    path = build_simple_cv(tmp_path / "cv.docx")
    first = [b.id for b in extract_blocks(path)]
    second = [b.id for b in extract_blocks(path)]
    assert first == second
    assert len(first) == len(set(first))  # all unique


def test_run_style_metadata_matches_source(tmp_path):
    path = build_simple_cv(tmp_path / "cv.docx")
    blocks = extract_blocks(path)
    by_text = {b.text: b for b in blocks}

    summary = by_text["Backend engineer with 8 years building payment systems."]
    assert summary.run_style.font == "Calibri"
    assert summary.run_style.size == 11.0
    assert summary.run_style.color == "#000000"

    title = by_text["Senior Engineer, Acme Corp"]
    assert title.run_style.bold is True

    bullet = by_text["Led migration of the billing service to a new provider."]
    assert bullet.run_style.italic is True


def test_paragraph_style_names_captured(tmp_path):
    path = build_simple_cv(tmp_path / "cv.docx")
    blocks = extract_blocks(path)
    by_text = {b.text: b for b in blocks}

    assert by_text["JOHN SMITH"].style_name == "Heading 1"
    assert by_text["Experience"].style_name == "Heading 2"
    assert (
        by_text["Led migration of the billing service to a new provider."].style_name
        == "List Bullet"
    )


def test_table_cells_captured_with_location(tmp_path):
    path = build_simple_cv(tmp_path / "cv.docx")
    blocks = extract_blocks(path)
    by_text = {b.text: b for b in blocks}

    python_block = by_text["Python"]
    postgres_block = by_text["PostgreSQL"]

    assert python_block.location.kind == "table_cell"
    assert python_block.location.table_index == 0
    assert python_block.location.row_index == 0
    assert python_block.location.cell_index == 0

    assert postgres_block.location.table_index == 0
    assert postgres_block.location.cell_index == 1


def test_does_not_crash_on_tables(tmp_path):
    path = build_simple_cv(tmp_path / "cv.docx")
    # Would raise if table handling were missing/broken.
    blocks = extract_blocks(path)
    assert len(blocks) > 0
