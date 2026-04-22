from __future__ import annotations

import pytest

from research_layer.services.argument_unit_extraction_service import (
    ArgumentUnitExtractionService,
)
from research_layer.services.llm_trace import LLMCallResult


class _FakeGateway:
    def __init__(self, parsed_json: dict[str, object] | None = None) -> None:
        self.kwargs: dict[str, object] = {}
        self.parsed_json = parsed_json or {
            "units": [
                {
                    "unit_id": "u1",
                    "semantic_type": "claim",
                    "text": "The intervention improved retrieval quality.",
                    "quote": "The intervention improved retrieval quality.",
                    "anchor": {"page": 1, "block_id": "p1-b0"},
                }
            ]
        }

    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        self.kwargs = kwargs
        return LLMCallResult(
            provider_backend="unit_test_backend",
            provider_model="unit_test_model",
            request_id=str(kwargs["request_id"]),
            llm_response_id="resp_argument_units",
            usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            raw_text='{"units":[]}',
            parsed_json=self.parsed_json,
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


@pytest.mark.asyncio
async def test_argument_unit_extractor_returns_prompt_b_units() -> None:
    gateway = _FakeGateway()
    units, trace = await ArgumentUnitExtractionService(gateway).extract_units(
        request_id="req_units",
        workspace_id="ws_units",
        source_id="src_units",
        source_title="Source",
        source_type="paper",
        chunk_id="chunk_src_units",
        chunk_text="The intervention improved retrieval quality.",
        anchor_refs=[{"page": 1, "block_id": "p1-b0"}],
        document_reading_memo="Read as an argument graph.",
        max_tokens=256,
        timeout_s=30,
        failure_mode=None,
    )

    assert trace.llm_response_id == "resp_argument_units"
    assert units == [
        {
            "unit_id": "u1",
            "semantic_type": "claim",
            "candidate_type": "conclusion",
            "text": "The intervention improved retrieval quality.",
            "quote": "The intervention improved retrieval quality.",
            "anchor": {"page": 1, "block_id": "p1-b0"},
        }
    ]


@pytest.mark.asyncio
async def test_argument_unit_prompt_limits_output_to_core_argument_units() -> None:
    gateway = _FakeGateway()

    await ArgumentUnitExtractionService(gateway).extract_units(
        request_id="req_units_budget",
        workspace_id="ws_units_budget",
        source_id="src_units_budget",
        source_title="Source",
        source_type="paper",
        chunk_id="chunk_src_units_budget",
        chunk_text="The report contains many repeated observations.",
        anchor_refs=[],
        document_reading_memo="Read as an argument graph.",
        max_tokens=256,
        timeout_s=30,
        failure_mode=None,
    )

    messages = gateway.kwargs["messages"]
    prompt_text = "\n".join(str(message.content) for message in messages)
    assert "at most 24" in prompt_text
    assert "core argument units" in prompt_text


@pytest.mark.asyncio
async def test_argument_unit_extractor_caps_dense_outputs() -> None:
    gateway = _FakeGateway(
        {
            "units": [
                {
                    "unit_id": f"u{index}",
                    "semantic_type": "claim",
                    "text": f"Claim {index}",
                    "quote": f"Claim {index}",
                    "anchor": {},
                }
                for index in range(1, 31)
            ]
        }
    )

    units, _trace = await ArgumentUnitExtractionService(gateway).extract_units(
        request_id="req_units_cap",
        workspace_id="ws_units_cap",
        source_id="src_units_cap",
        source_title="Source",
        source_type="paper",
        chunk_id="chunk_src_units_cap",
        chunk_text="Many repeated claims.",
        anchor_refs=[],
        document_reading_memo="Read as an argument graph.",
        max_tokens=256,
        timeout_s=30,
        failure_mode=None,
    )

    assert len(units) == 24
    assert units[-1]["unit_id"] == "u24"
