from __future__ import annotations

import pytest

from research_layer.services.argument_unit_extraction_service import (
    ArgumentUnitExtractionService,
)
from research_layer.services.llm_trace import LLMCallResult


class _FakeGateway:
    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        return LLMCallResult(
            provider_backend="unit_test_backend",
            provider_model="unit_test_model",
            request_id=str(kwargs["request_id"]),
            llm_response_id="resp_argument_units",
            usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            raw_text='{"units":[]}',
            parsed_json={
                "units": [
                    {
                        "unit_id": "u1",
                        "semantic_type": "claim",
                        "text": "The intervention improved retrieval quality.",
                        "quote": "The intervention improved retrieval quality.",
                        "anchor": {"page": 1, "block_id": "p1-b0"},
                    }
                ]
            },
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


@pytest.mark.asyncio
async def test_argument_unit_extractor_returns_prompt_b_units() -> None:
    units, trace = await ArgumentUnitExtractionService(_FakeGateway()).extract_units(
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
