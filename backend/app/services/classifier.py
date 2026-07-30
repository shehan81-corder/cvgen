"""Stage 0: deterministic editable/fixed classification of blocks.

Rules and rationale: architecture.md §4. This never calls the LLM — it's
plain heuristics over paragraph style names and regexes, run once per
uploaded document at upload time (see app/routers/sessions.py).
"""

from __future__ import annotations

import re
from typing import Literal

from app.services.docx_blocks import Block

SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "experience": ("experience", "work history", "employment"),
    "summary": ("summary", "profile", "objective"),
    "highlights": ("career highlights", "key achievements", "achievements", "highlights"),
    "skills": ("skills", "technical skills", "core competencies"),
    "projects": ("projects", "personal projects"),
    "education": ("education", "academic background"),
    "certifications": ("certifications", "certificates", "licenses"),
    "contact": ("contact",),
}

EDITABLE_SECTIONS = {"experience", "summary", "highlights", "skills", "projects"}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.\w+")
PHONE_RE = re.compile(r"(\+?\d[\d\-\s().]{6,}\d)")
URL_RE = re.compile(r"(https?://|www\.)\S+|linkedin\.com/\S+", re.IGNORECASE)
DATE_RE = re.compile(
    r"\b(19|20)\d{2}\b"
    r"|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}\b"
    r"|\b(present|current)\b",
    re.IGNORECASE,
)

_BULLET_STYLE_HINTS = ("bullet", "list")
_BULLET_CHARS = ("•", "-", "*", "◦")
_SENTENCE_END = (".", "!", "?")

_SALUTATION_RE = re.compile(r"^(dear\b|to whom it may concern)", re.IGNORECASE)
_SIGNOFF_RE = re.compile(
    r"^(yours sincerely|yours faithfully|sincerely|regards|kind regards|best regards|warm regards)\b",
    re.IGNORECASE,
)
# Cover letters have no CV-style section headings, so body prose is told
# apart from letterhead/address/subject-line fragments by length alone —
# short fragments ("Melbourne", "Re: Engineering Manager") stay fixed,
# genuine sentences don't. See classify_blocks' cover_letter branch.
_COVER_LETTER_BODY_MIN_WORDS = 6


def _is_heading(text: str, style_name: str | None, *, paragraph_leading: bool = True) -> bool:
    if style_name and "heading" in style_name.lower():
        return True
    if not paragraph_leading:
        # An all-caps run that isn't at the start of its paragraph is an
        # inline acronym or a mid-word run-split fragment (e.g. "GCP" inside
        # a bullet, or the "S" left over when "TypeScript" gets split across
        # runs) — not a section heading. Without this gate, one such fragment
        # anywhere in the document silently resets section-tracking, turning
        # everything after it `fixed` until the next real heading. Found on
        # a real CV where this excluded ~90 of ~130 experience/skills blocks
        # from tailoring. See architecture.md §4.
        return False
    stripped = text.strip()
    if not stripped or not any(c.isalpha() for c in stripped):
        return False
    if "," in stripped:
        # A short all-caps comma-separated value (e.g. "AWS, GCP" in a skills
        # table) would otherwise be misdetected as an all-caps section marker
        # like "SKILLS" — found via I1's classifier fixture re-run.
        return False
    words = stripped.split()
    return stripped == stripped.upper() and 1 <= len(words) <= 4


def _paragraph_key(location) -> tuple:
    return (
        location.kind,
        location.table_index,
        location.row_index,
        location.cell_index,
        location.paragraph_index,
    )


def _match_section(text: str) -> str | None:
    lowered = text.lower()
    for section, aliases in SECTION_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return section
    return None


def _looks_like_title_line(text: str, style_name: str | None) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if style_name and any(hint in style_name.lower() for hint in _BULLET_STYLE_HINTS):
        return False
    if stripped[0] in _BULLET_CHARS:
        return False
    if stripped.endswith(_SENTENCE_END):
        return False
    # Require >=2 words so a single short skill/table-cell word (e.g. "Python")
    # isn't mistaken for a "Title, Company" shaped line.
    words = stripped.split()
    if not (2 <= len(words) <= 8):
        return False
    return stripped[0].isupper()


def classify_blocks(
    blocks: list[Block], document_type: Literal["cv", "cover_letter"] = "cv"
) -> list[Block]:
    """Return a new list of blocks annotated with `section` and `editable`.

    For `cv`: applies rules in order (architecture.md §4): section-boundary/
    heading detection, then fixed patterns (contact info, dates, title/
    company shaped lines), then a section-based default. Unrecognized or
    unestablished sections default to `fixed` — conservative on purpose,
    see architecture.md §4's documented limitation.

    For `cover_letter`: cover letters have no CV-style section headings
    (no "Experience"/"Skills"), so the CV's section-based default would
    leave the entire letter classified `fixed` — found via I1's real-CV
    acceptance run. Instead, fixed patterns (contact info, dates,
    salutation, sign-off) are still protected, but everything else
    defaults to `editable` when it's long enough to be genuine body prose
    rather than a short letterhead/address/subject-line fragment.
    """
    current_section: str | None = None
    classified: list[Block] = []
    prev_paragraph_key: tuple | None = None
    paragraph_leading = True

    for block in blocks:
        text = block.text
        style_name = block.style_name
        stripped = text.strip()

        paragraph_key = _paragraph_key(block.location)
        if paragraph_key != prev_paragraph_key:
            prev_paragraph_key = paragraph_key
            paragraph_leading = True
        is_heading_here = _is_heading(text, style_name, paragraph_leading=paragraph_leading)
        if any(c.islower() for c in text):
            paragraph_leading = False

        if EMAIL_RE.search(text) or PHONE_RE.search(text) or URL_RE.search(text):
            classified.append(
                block.model_copy(update={"section": current_section or "contact", "editable": False})
            )
            continue

        if DATE_RE.search(text):
            classified.append(block.model_copy(update={"section": current_section, "editable": False}))
            continue

        if document_type == "cover_letter":
            if _SALUTATION_RE.match(stripped) or _SIGNOFF_RE.match(stripped):
                classified.append(block.model_copy(update={"section": "letter", "editable": False}))
                continue
            if is_heading_here:
                classified.append(block.model_copy(update={"section": "unknown", "editable": False}))
                continue
            editable = len(stripped.split()) >= _COVER_LETTER_BODY_MIN_WORDS
            classified.append(
                block.model_copy(update={"section": "body", "editable": editable})
            )
            continue

        if is_heading_here:
            matched = _match_section(text)
            current_section = matched
            classified.append(
                block.model_copy(update={"section": matched or "unknown", "editable": False})
            )
            continue

        if current_section in ("experience", "education") and _looks_like_title_line(text, style_name):
            classified.append(block.model_copy(update={"section": current_section, "editable": False}))
            continue

        editable = current_section in EDITABLE_SECTIONS
        classified.append(
            block.model_copy(update={"section": current_section or "unknown", "editable": editable})
        )

    return classified
