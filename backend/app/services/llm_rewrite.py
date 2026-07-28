"""Stage 1: sparse-diff LLM rewrite over `editable` blocks only.

Design and rationale: architecture.md §5. This never sees `fixed` blocks
(dates, headers, titles, contact info) — they're excluded by the caller
before this module is invoked, which is what makes the "don't touch
structure/dates/titles" guarantee structural rather than prompt-only.
"""

from __future__ import annotations

from dataclasses import dataclass

import anthropic

from app.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
from app.services.docx_blocks import Block

SYSTEM_PROMPT = """\
You help tailor a CV (and optionally a cover letter) to a specific job \
description. You will be given the job description and a list of text \
blocks from the candidate's existing document, each with a stable id. \
You must follow these rules exactly:

- Only adjust wording to better reflect skills, terms, or priorities from \
the job description where truthfully applicable to what the candidate has \
already written. Never invent skills, experience, tools, or claims that \
aren't already present in some form in the original text.
- Preserve the original sentence structure and logical flow of each block. \
This is light editing — swap a word or phrase, adjust emphasis — never a \
full rewrite of a block.
- Preserve the candidate's existing tone and vocabulary level. Reuse their \
own words wherever possible.
- Never introduce AI/marketing buzzwords or jargon that isn't already in \
the source text or job description. Examples of words to never introduce: \
"synergize", "leverage", "spearheaded", "results-driven", "dynamic", \
"cutting-edge", "passionate", "proven track record".
- Use plain, simple, human language. The result must not read as \
AI-generated, robotic, or overly polished.
- Every block you receive is already filtered to only the content that is \
appropriate to edit (bullets, summaries, skills). Do not attempt to add, \
remove, merge, split, or reorder blocks — only edit the text of a block in \
place if it is worth changing.
- Only return blocks you actually change. If a block doesn't need to \
change, leave it out of your response entirely — do not echo it back.
- It is entirely valid to change nothing. If none of the blocks benefit \
from tailoring, return empty edit lists.

Use the return_edits tool to give your answer."""

_TOOL_NAME = "return_edits"

_EDIT_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "The block id being changed."},
        "text": {"type": "string", "description": "The full replacement text for this block."},
    },
    "required": ["id", "text"],
}

_TOOL_SCHEMA = {
    "name": _TOOL_NAME,
    "description": "Return only the blocks you changed, for the CV and (if provided) the cover letter.",
    "input_schema": {
        "type": "object",
        "properties": {
            "cv_edits": {"type": "array", "items": _EDIT_ITEM_SCHEMA},
            "cover_letter_edits": {"type": "array", "items": _EDIT_ITEM_SCHEMA},
        },
        "required": ["cv_edits"],
    },
}


@dataclass
class BlockEdit:
    id: str
    text: str


@dataclass
class GenerationResult:
    cv_edits: list[BlockEdit]
    cover_letter_edits: list[BlockEdit] | None
    low_confidence: bool
    usage: dict


class LLMGenerationError(Exception):
    pass


class InvalidEditIdsError(LLMGenerationError):
    def __init__(self, document: str, invalid_ids: list[str]):
        self.document = document
        self.invalid_ids = invalid_ids
        super().__init__(
            f"Model returned edits for {document} block ids outside the "
            f"editable set: {invalid_ids}"
        )


def _format_blocks(blocks: list[Block]) -> str:
    return "\n".join(f"[{b.id}] {b.text}" for b in blocks)


def _build_user_content(
    job_description: str,
    cv_blocks: list[Block],
    cover_letter_blocks: list[Block] | None,
) -> list[dict]:
    context_parts = [
        "JOB DESCRIPTION:",
        job_description.strip(),
        "",
        "CV BLOCKS (id: text):",
        _format_blocks(cv_blocks),
    ]
    if cover_letter_blocks:
        context_parts += [
            "",
            "COVER LETTER BLOCKS (id: text):",
            _format_blocks(cover_letter_blocks),
        ]
    context_block = "\n".join(context_parts)

    return [
        {"type": "text", "text": context_block, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "Produce your edits now using the return_edits tool."},
    ]


def _parse_edits(raw_items: list[dict]) -> list[BlockEdit]:
    return [BlockEdit(id=item["id"], text=item["text"]) for item in raw_items]


def _validate_ids(document: str, edits: list[BlockEdit], allowed_ids: set[str]) -> None:
    invalid = [e.id for e in edits if e.id not in allowed_ids]
    if invalid:
        raise InvalidEditIdsError(document, invalid)


def generate_tailored_edits(
    job_description: str,
    cv_editable_blocks: list[Block],
    cover_letter_editable_blocks: list[Block] | None = None,
    *,
    client: anthropic.Anthropic | None = None,
) -> GenerationResult:
    """Call Claude once for the CV (and cover letter, if given) and return
    the sparse set of block edits. Raises InvalidEditIdsError if the model
    returns an id outside the editable set it was sent (spec.md §11).
    """
    active_client = client or anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = active_client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
        messages=[
            {
                "role": "user",
                "content": _build_user_content(
                    job_description, cv_editable_blocks, cover_letter_editable_blocks
                ),
            }
        ],
    )

    tool_use = next((b for b in message.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise LLMGenerationError("Model did not return a tool_use block.")

    tool_input = tool_use.input
    cv_edits = _parse_edits(tool_input.get("cv_edits", []))
    _validate_ids("cv", cv_edits, {b.id for b in cv_editable_blocks})

    cover_letter_edits: list[BlockEdit] | None = None
    if cover_letter_editable_blocks is not None:
        cover_letter_edits = _parse_edits(tool_input.get("cover_letter_edits", []))
        _validate_ids(
            "cover_letter", cover_letter_edits, {b.id for b in cover_letter_editable_blocks}
        )

    total_edits = len(cv_edits) + len(cover_letter_edits or [])
    usage = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "cache_read_input_tokens": getattr(message.usage, "cache_read_input_tokens", None),
        "cache_creation_input_tokens": getattr(message.usage, "cache_creation_input_tokens", None),
    }

    return GenerationResult(
        cv_edits=cv_edits,
        cover_letter_edits=cover_letter_edits,
        low_confidence=(total_edits == 0),
        usage=usage,
    )
