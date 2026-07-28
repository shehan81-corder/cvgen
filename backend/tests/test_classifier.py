from app.services.classifier import classify_blocks
from app.services.docx_blocks import extract_blocks
from tests.docx_fixtures import (
    build_cv_no_heading_styles,
    build_cv_with_skills_table,
    build_simple_cv,
)


def _classify(path):
    return {b.text: b for b in classify_blocks(extract_blocks(path))}


def test_dates_are_always_fixed(tmp_path):
    by_text = _classify(build_simple_cv(tmp_path / "cv.docx"))
    assert by_text["Jan 2020 - Present"].editable is False


def test_contact_info_is_always_fixed(tmp_path):
    by_text = _classify(build_simple_cv(tmp_path / "cv.docx"))
    contact = by_text["john.smith@example.com | +1 555-123-4567"]
    assert contact.editable is False


def test_section_headings_are_fixed_and_set_section_context(tmp_path):
    by_text = _classify(build_simple_cv(tmp_path / "cv.docx"))
    assert by_text["Summary"].editable is False
    assert by_text["Summary"].section == "summary"
    assert by_text["Experience"].editable is False
    assert by_text["Experience"].section == "experience"


def test_job_title_line_is_fixed(tmp_path):
    by_text = _classify(build_simple_cv(tmp_path / "cv.docx"))
    title = by_text["Senior Engineer, Acme Corp"]
    assert title.editable is False
    assert title.section == "experience"


def test_summary_and_bullet_content_is_editable(tmp_path):
    by_text = _classify(build_simple_cv(tmp_path / "cv.docx"))
    summary = by_text["Backend engineer with 8 years building payment systems."]
    assert summary.editable is True
    assert summary.section == "summary"

    bullet = by_text["Led migration of the billing service to a new provider."]
    assert bullet.editable is True
    assert bullet.section == "experience"


def test_skills_table_inherits_section_from_preceding_heading(tmp_path):
    by_text = _classify(build_cv_with_skills_table(tmp_path / "cv.docx"))
    languages_value = by_text["Python, Go"]
    assert languages_value.section == "skills"
    assert languages_value.editable is True


def test_degree_line_under_education_is_fixed(tmp_path):
    by_text = _classify(build_cv_with_skills_table(tmp_path / "cv.docx"))
    degree = by_text["BSc Computer Science, State University"]
    assert degree.editable is False
    assert degree.section == "education"


def test_all_caps_section_marker_without_heading_style_is_detected(tmp_path):
    by_text = _classify(build_cv_no_heading_styles(tmp_path / "cv.docx"))
    experience_marker = by_text["EXPERIENCE"]
    assert experience_marker.editable is False
    assert experience_marker.section == "experience"

    title = by_text["Product Manager, Globex Inc"]
    assert title.editable is False
    assert title.section == "experience"

    bullet = by_text["Managed a team of five designers and engineers."]
    assert bullet.editable is True
    assert bullet.section == "experience"


def test_unrecognized_or_unestablished_section_defaults_to_fixed(tmp_path):
    """Documents the conservative default from architecture.md §4: a block
    with no established/recognized section is left `fixed` rather than
    risking an edit somewhere unexpected."""
    by_text = _classify(build_simple_cv(tmp_path / "cv.docx"))
    name = by_text["JOHN SMITH"]
    assert name.section == "unknown"
    assert name.editable is False  # heading, always fixed regardless of section
