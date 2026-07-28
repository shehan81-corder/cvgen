from app.services.classifier import classify_blocks
from app.services.docx_blocks import extract_blocks
from app.services.docx_writer import (
    apply_edits_to_docx,
    build_preview,
    make_output_filename,
    tailored_text,
)
from app.services.llm_rewrite import BlockEdit
from tests.docx_fixtures import build_simple_cv


def test_empty_diff_round_trips_identically(tmp_path):
    source = build_simple_cv(tmp_path / "cv.docx")
    output = tmp_path / "output.docx"

    blocks = extract_blocks(source)
    apply_edits_to_docx(source, blocks, edits=[], output_path=output)

    original_blocks = extract_blocks(source)
    output_blocks = extract_blocks(output)

    assert [b.text for b in output_blocks] == [b.text for b in original_blocks]
    assert [b.style_name for b in output_blocks] == [b.style_name for b in original_blocks]
    assert [b.run_style for b in output_blocks] == [b.run_style for b in original_blocks]


def test_edit_changes_only_targeted_block_and_preserves_its_formatting(tmp_path):
    source = build_simple_cv(tmp_path / "cv.docx")
    output = tmp_path / "output.docx"

    blocks = extract_blocks(source)
    bullet_block = next(
        b for b in blocks if b.text == "Led migration of the billing service to a new provider."
    )
    edits = [BlockEdit(id=bullet_block.id, text="Led migration of the payments service to a new vendor.")]
    apply_edits_to_docx(source, blocks, edits, output)

    original_blocks = {b.id: b for b in extract_blocks(source)}
    output_blocks = {b.id: b for b in extract_blocks(output)}

    for block_id, output_block in output_blocks.items():
        original_block = original_blocks[block_id]
        if block_id == bullet_block.id:
            assert output_block.text == "Led migration of the payments service to a new vendor."
            # formatting (italic, per the fixture) untouched despite the text change
            assert output_block.run_style.italic == original_block.run_style.italic is True
        else:
            assert output_block.text == original_block.text
            assert output_block.run_style == original_block.run_style


def test_build_preview_flags_changed_and_unchanged_blocks(tmp_path):
    source = build_simple_cv(tmp_path / "cv.docx")
    blocks = classify_blocks(extract_blocks(source))
    title_block = next(b for b in blocks if b.text == "Senior Engineer, Acme Corp")
    bullet_block = next(
        b for b in blocks if b.text == "Led migration of the billing service to a new provider."
    )

    edits = [BlockEdit(id=bullet_block.id, text="Led migration of the payments service.")]
    preview = build_preview(blocks, edits)
    by_id = {p["id"]: p for p in preview}

    changed_entry = by_id[bullet_block.id]
    assert changed_entry["changed"] is True
    assert changed_entry["tailored_text"] == "Led migration of the payments service."
    assert changed_entry["original_text"] == "Led migration of the billing service to a new provider."
    assert changed_entry["editable"] is True

    fixed_entry = by_id[title_block.id]
    assert fixed_entry["changed"] is False
    assert fixed_entry["editable"] is False
    assert fixed_entry["tailored_text"] == fixed_entry["original_text"]


def test_tailored_text_reflects_edits():
    from app.services.docx_blocks import Block, BlockLocation, RunStyle

    blocks = [
        Block(
            id="a",
            text="one",
            location=BlockLocation(kind="paragraph", paragraph_index=0, run_index=0),
            run_style=RunStyle(),
        ),
        Block(
            id="b",
            text="two",
            location=BlockLocation(kind="paragraph", paragraph_index=1, run_index=0),
            run_style=RunStyle(),
        ),
    ]
    edits = [BlockEdit(id="b", text="TWO-EDITED")]
    assert tailored_text(blocks, edits) == "one TWO-EDITED"


def test_make_output_filename_matches_convention():
    filename = make_output_filename("my_cv.docx", "Senior Backend Engineer\nOther details")
    assert filename == "my_cv-tailored-senior-backend-engineer.docx"
