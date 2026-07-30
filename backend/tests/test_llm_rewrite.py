import pytest

from app.services.docx_blocks import Block, BlockLocation, RunStyle
from app.services.llm_rewrite import (
    BlockEdit,
    InvalidEditIdsError,
    LLMGenerationError,
    generate_tailored_edits,
)


def _block(block_id: str, text: str) -> Block:
    return Block(
        id=block_id,
        text=text,
        style_name="Normal",
        location=BlockLocation(kind="paragraph", paragraph_index=0, run_index=0),
        run_style=RunStyle(),
        section="experience",
        editable=True,
    )


class FakeUsage:
    def __init__(self):
        self.input_tokens = 500
        self.output_tokens = 50
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 480


class FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, input_data: dict):
        self.input = input_data


class FakeMessage:
    def __init__(self, tool_input: dict):
        self.content = [FakeToolUseBlock(tool_input)]
        self.usage = FakeUsage()


class FakeMessagesAPI:
    def __init__(self, tool_input: dict):
        self._tool_input = tool_input
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return FakeMessage(self._tool_input)


class FakeClient:
    def __init__(self, tool_input: dict):
        self.messages = FakeMessagesAPI(tool_input)


def test_valid_sparse_response_parsed_correctly():
    cv_blocks = [_block("p0-r0", "Led a small team."), _block("p1-r0", "Wrote some code.")]
    client = FakeClient({"cv_edits": [{"id": "p0-r0", "text": "Led a team of five engineers."}]})

    result = generate_tailored_edits("Looking for a lead engineer.", cv_blocks, client=client)

    assert result.cv_edits == [BlockEdit(id="p0-r0", text="Led a team of five engineers.")]
    assert result.cover_letter_edits is None
    assert result.low_confidence is False


def test_invalid_cv_edit_id_raises():
    cv_blocks = [_block("p0-r0", "Led a small team.")]
    client = FakeClient({"cv_edits": [{"id": "not-a-real-id", "text": "x"}]})

    with pytest.raises(InvalidEditIdsError) as exc_info:
        generate_tailored_edits("JD text", cv_blocks, client=client)

    assert exc_info.value.document == "cv"
    assert exc_info.value.invalid_ids == ["not-a-real-id"]


def test_empty_edits_are_valid_but_flagged_low_confidence():
    cv_blocks = [_block("p0-r0", "Led a small team.")]
    client = FakeClient({"cv_edits": []})

    result = generate_tailored_edits("JD text", cv_blocks, client=client)

    assert result.cv_edits == []
    assert result.low_confidence is True


def test_cover_letter_edits_parsed_and_validated_independently():
    cv_blocks = [_block("p0-r0", "Led a small team.")]
    cl_blocks = [_block("p5-r0", "I am excited to apply.")]
    client = FakeClient(
        {
            "cv_edits": [{"id": "p0-r0", "text": "Led a cross-functional team."}],
            "cover_letter_edits": [{"id": "p5-r0", "text": "I'm keen to apply."}],
        }
    )

    result = generate_tailored_edits(
        "JD text", cv_blocks, cover_letter_editable_blocks=cl_blocks, client=client
    )

    assert result.cv_edits == [BlockEdit(id="p0-r0", text="Led a cross-functional team.")]
    assert result.cover_letter_edits == [BlockEdit(id="p5-r0", text="I'm keen to apply.")]
    assert result.low_confidence is False


def test_cover_letter_invalid_id_raises_with_correct_document_label():
    cv_blocks = [_block("p0-r0", "Led a small team.")]
    cl_blocks = [_block("p5-r0", "I am excited to apply.")]
    client = FakeClient(
        {
            "cv_edits": [],
            "cover_letter_edits": [{"id": "bogus-id", "text": "x"}],
        }
    )

    with pytest.raises(InvalidEditIdsError) as exc_info:
        generate_tailored_edits(
            "JD text", cv_blocks, cover_letter_editable_blocks=cl_blocks, client=client
        )

    assert exc_info.value.document == "cover_letter"
    assert exc_info.value.invalid_ids == ["bogus-id"]


def test_request_is_a_single_combined_call_with_caching_and_forced_tool_use():
    cv_blocks = [_block("p0-r0", "Led a small team.")]
    cl_blocks = [_block("p5-r0", "I am excited to apply.")]
    client = FakeClient(
        {"cv_edits": [], "cover_letter_edits": [{"id": "p5-r0", "text": "Updated."}]}
    )

    generate_tailored_edits(
        "JD text", cv_blocks, cover_letter_editable_blocks=cl_blocks, client=client
    )

    kwargs = client.messages.last_kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "return_edits"}
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}

    user_content = kwargs["messages"][0]["content"]
    context_text = user_content[0]["text"]
    assert user_content[0]["cache_control"] == {"type": "ephemeral"}
    assert "p0-r0" in context_text  # CV block present
    assert "p5-r0" in context_text  # cover letter block present in the SAME call
    assert "JD text" in context_text


def test_low_confidence_false_when_only_cover_letter_has_edits():
    cv_blocks = [_block("p0-r0", "Led a small team.")]
    cl_blocks = [_block("p5-r0", "I am excited to apply.")]
    client = FakeClient(
        {"cv_edits": [], "cover_letter_edits": [{"id": "p5-r0", "text": "Updated."}]}
    )

    result = generate_tailored_edits(
        "JD text", cv_blocks, cover_letter_editable_blocks=cl_blocks, client=client
    )

    assert result.low_confidence is False


def test_empty_cover_letter_edits_raises_when_cover_letter_blocks_provided():
    # Belt-and-suspenders check: the job title/company reference in a cover
    # letter must always be corrected (SYSTEM_PROMPT), enforced primarily via
    # the tool schema's minItems — but if the model still returns an empty
    # array despite cover letter blocks being sent, that's treated as a
    # retryable failure rather than silently shipping a stale reference.
    cv_blocks = [_block("p0-r0", "Led a small team.")]
    cl_blocks = [_block("p5-r0", "I am excited to apply.")]
    client = FakeClient({"cv_edits": [], "cover_letter_edits": []})

    with pytest.raises(LLMGenerationError):
        generate_tailored_edits(
            "JD text", cv_blocks, cover_letter_editable_blocks=cl_blocks, client=client
        )


def test_empty_cover_letter_edits_allowed_when_no_editable_cover_letter_blocks():
    # A cover letter was uploaded but ended up with zero editable blocks
    # (e.g. entirely fixed content) — nothing to require an edit against.
    cv_blocks = [_block("p0-r0", "Led a small team.")]
    client = FakeClient({"cv_edits": [], "cover_letter_edits": []})

    result = generate_tailored_edits(
        "JD text", cv_blocks, cover_letter_editable_blocks=[], client=client
    )

    assert result.cover_letter_edits == []


def test_tool_schema_requires_cover_letter_edits_when_cover_letter_blocks_present():
    cv_blocks = [_block("p0-r0", "Led a small team.")]
    cl_blocks = [_block("p5-r0", "I am excited to apply.")]
    client = FakeClient(
        {"cv_edits": [], "cover_letter_edits": [{"id": "p5-r0", "text": "Updated."}]}
    )

    generate_tailored_edits(
        "JD text", cv_blocks, cover_letter_editable_blocks=cl_blocks, client=client
    )

    schema = client.messages.last_kwargs["tools"][0]["input_schema"]
    assert "cover_letter_edits" in schema["required"]
    assert schema["properties"]["cover_letter_edits"]["minItems"] == 1


def test_tool_schema_does_not_require_cover_letter_edits_when_no_cover_letter():
    cv_blocks = [_block("p0-r0", "Led a small team.")]
    client = FakeClient({"cv_edits": []})

    generate_tailored_edits("JD text", cv_blocks, client=client)

    schema = client.messages.last_kwargs["tools"][0]["input_schema"]
    assert "cover_letter_edits" not in schema["required"]
    assert "minItems" not in schema["properties"]["cover_letter_edits"]
