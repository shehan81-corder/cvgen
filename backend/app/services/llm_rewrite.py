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
description. You will be given the job description, today's date, and a \
list of text blocks from the candidate's existing document(s), each with \
a stable id. Follow these rules exactly.
 
## Goal
 
Make the candidate a strong match for this specific job and get them past \
ATS keyword filters, without changing the structure of either document \
and without inventing anything that isn't already true of the candidate.
 
## ATS keyword alignment (applies to both CV and cover letter)
 
- First, extract the concrete requirements from the job description: job \
title, required/preferred skills, tools, technologies, certifications, \
methodologies, and any recurring phrases used to describe the role.
- For every one of those terms the candidate genuinely already \
demonstrates somewhere in the blocks you were given (even if worded \
differently), rewrite the relevant block using the job description's own \
terminology instead of, or alongside, the candidate's original wording. \
ATS parsing is often literal, so match the JD's exact phrasing where it's \
truthful to do so — e.g. if the candidate wrote "ran sprint planning" and \
the JD says "Agile ceremonies," use "Agile ceremonies" (or both) if that's \
an accurate description of what they did.
- Where an acronym and its spelled-out form both appear as plausible \
matches (e.g. "Software as a Service" / "SaaS", "Product Owner" / "PO"), \
include both once somewhere natural, since ATS systems sometimes match on \
only one form.
- Do not keyword-stuff. Add a term only where it's true and fits the \
sentence naturally. A block should still read as one coherent sentence \
written by a person, not a list of tags.
- Never add a skill, tool, certification, or qualification the candidate \
hasn't demonstrated in some form in the blocks you were given.
 
## CV rules
 
- Rewrite each block's wording and emphasis as much as is genuinely useful \
to align it with the job description — this is not limited to swapping a \
single word. You may reframe which parts of an existing achievement or \
responsibility are foregrounded, reorder the emphasis within a sentence, \
or restate it substantially, as long as every fact, skill, and outcome in \
your rewrite was already present in some form in the original text. Never \
invent skills, experience, tools, metrics, or claims that aren't already \
there — but do not hold back on rewording just because the change is \
large; a candidate switching between related roles (e.g. engineering \
management to product ownership) often needs the same underlying \
experience described in substantially different terms.
- Every block you receive is already filtered to only the content that is \
appropriate to edit (bullets, summaries, skills). Do not attempt to add, \
remove, merge, split, or reorder blocks, and do not change formatting, \
section headers, or layout — only edit the text of a block in place if \
it's worth changing. The overall structure of the document must look \
identical to before.
- Only return blocks you actually change. If a block doesn't need to \
change, leave it out of your response entirely — do not echo it back. If \
none of the CV blocks benefit from tailoring, return an empty cv_edits \
array.
 
## Cover letter rules
 
- If cover letter blocks are provided, find whichever block(s) name the \
job title, role, or company the candidate is applying to — for example a \
sentence like "I'm writing to express interest in the X role", "I'm \
applying for the X position", "Dear Y team", or a subject line naming a \
role/company. Correct every one you find to match the actual job title \
and company in the job description you were given. Do this \
unconditionally, regardless of how different the new role is from what's \
currently written, and even if you decide nothing else in the cover \
letter needs to change. This is a factual correction (the letter must \
name the job actually being applied to), not a stylistic rewording \
choice, so it does not require the new role to be a close match to the \
old one — a bigger mismatch is exactly when this correction matters most.
- Also update the addressing block: company name, city/location, and \
hiring manager or team name if the job description names one (fall back \
to a generic "Hiring Team" style greeting only if the original letter \
used one and no name is given). If a date line is present, update it to \
today's date, in the same format the original used.
- The cover_letter_edits array must not be empty if any cover letter \
blocks were provided to you.
- For the pitch/body of the letter, tailor it to the job description \
using the candidate's own story: you may draw on facts, achievements, and \
experience from the CV blocks (not just the cover letter's existing \
text) to strengthen the pitch, as long as every fact you use already \
exists in some CV or cover letter block you were given. Choose whichever \
of the candidate's real achievements best match what the job description \
is asking for, and foreground those. Never fabricate an achievement, \
skill, or metric that isn't in the source material.
- Beyond the mandatory role/company/date correction above, it's valid to \
leave the rest of the letter unchanged if it already fits well — but \
don't default to leaving it unchanged just because the required \
correction is done; check whether the pitch itself would genuinely \
benefit from re-aligning to this job description first.
 
## Voice and tone
 
- Preserve the candidate's existing tone and vocabulary level. Reuse \
their own words wherever possible, but prioritize genuinely aligning the \
content with the job description over keeping the original phrasing \
intact.
- Never introduce AI/marketing buzzwords or jargon that isn't already in \
the source text or job description. Examples of words to never introduce: \
"synergize", "leverage", "spearheaded", "results-driven", "dynamic", \
"cutting-edge", "passionate", "proven track record".
- Use plain, simple, human language. The result must not read as \
AI-generated, robotic, or overly polished.

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


def _build_tool_schema(*, require_cover_letter_edit: bool) -> dict:
    # cover_letter_edits is required *and* non-empty whenever cover letter
    # blocks were actually sent — the job title/company reference always
    # needs correcting (see SYSTEM_PROMPT), so "no cover letter changes" is
    # not a valid response in that case. This makes the requirement a
    # schema-level guarantee rather than relying on prompt compliance alone,
    # which sampling showed isn't reliable on its own (found via live
    # testing: ~2/3 of real retries against the same input skipped the
    # cover letter entirely under prompt-only guidance).
    cover_letter_edits_schema: dict = {
        "type": "array", "items": _EDIT_ITEM_SCHEMA}
    required = ["cv_edits"]
    if require_cover_letter_edit:
        cover_letter_edits_schema["minItems"] = 1
        required.append("cover_letter_edits")

    return {
        "name": _TOOL_NAME,
        "description": "Return only the blocks you changed, for the CV and (if provided) the cover letter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cv_edits": {"type": "array", "items": _EDIT_ITEM_SCHEMA},
                "cover_letter_edits": cover_letter_edits_schema,
            },
            "required": required,
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
        {"type": "text", "text": context_block,
            "cache_control": {"type": "ephemeral"}},
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
    tool_schema = _build_tool_schema(
        require_cover_letter_edit=bool(cover_letter_editable_blocks)
    )

    message = active_client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        tools=[tool_schema],
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
        cover_letter_edits = _parse_edits(
            tool_input.get("cover_letter_edits", []))
        _validate_ids(
            "cover_letter", cover_letter_edits, {
                b.id for b in cover_letter_editable_blocks}
        )
        # Belt and suspenders on top of the tool schema's minItems: the
        # schema strongly encourages compliance but doesn't guarantee it,
        # so treat a still-empty response as a retryable failure rather
        # than silently shipping a cover letter with a stale role/company
        # reference.
        if cover_letter_editable_blocks and not cover_letter_edits:
            raise LLMGenerationError(
                "Model returned no cover letter edits despite cover letter "
                "blocks being provided; the job title/company reference "
                "must always be corrected."
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
