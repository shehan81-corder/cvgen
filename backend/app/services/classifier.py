"""Stage 0: deterministic editable/fixed classification of blocks.

Rules and rationale: architecture.md §4. This never calls the LLM — it's
plain heuristics over paragraph style names and regexes, run once per
uploaded document at upload time (see app/routers/sessions.py).
"""

from __future__ import annotations

import re

from app.services.docx_blocks import Block

SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "experience": ("experience", "work history", "employment"),
    "summary": ("summary", "profile", "objective"),
    "skills": ("skills", "technical skills", "core competencies"),
    "projects": ("projects", "personal projects"),
    "education": ("education", "academic background"),
    "certifications": ("certifications", "certificates", "licenses"),
    "contact": ("contact",),
}

EDITABLE_SECTIONS = {"experience", "summary", "skills", "projects"}

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


def _is_heading(text: str, style_name: str | None) -> bool:
    if style_name and "heading" in style_name.lower():
        return True
    stripped = text.strip()
    if not stripped or not any(c.isalpha() for c in stripped):
        return False
    words = stripped.split()
    return stripped == stripped.upper() and 1 <= len(words) <= 4


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


def classify_blocks(blocks: list[Block]) -> list[Block]:
    """Return a new list of blocks annotated with `section` and `editable`.

    Applies rules in order (architecture.md §4): section-boundary/heading
    detection, then fixed patterns (contact info, dates, title/company
    shaped lines), then a section-based default. Unrecognized or
    unestablished sections default to `fixed` — conservative on purpose,
    see architecture.md §4's documented limitation.
    """
    current_section: str | None = None
    classified: list[Block] = []

    for block in blocks:
        text = block.text
        style_name = block.style_name

        if EMAIL_RE.search(text) or PHONE_RE.search(text) or URL_RE.search(text):
            classified.append(
                block.model_copy(update={"section": current_section or "contact", "editable": False})
            )
            continue

        if DATE_RE.search(text):
            classified.append(block.model_copy(update={"section": current_section, "editable": False}))
            continue

        if _is_heading(text, style_name):
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
