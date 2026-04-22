from __future__ import annotations

import pytest

from research_layer.services.llm_trace import LLMCallResult
from research_layer.services.relation_extraction_service import (
    RelationExtractionService,
)


class _FakeGateway:
    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        return LLMCallResult(
            provider_backend="unit_test_backend",
            provider_model="unit_test_model",
            request_id=str(kwargs["request_id"]),
            llm_response_id="resp_argument_relations",
            usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            raw_text='{"relations":[]}',
            parsed_json={
                "relations": [
                    {
                        "source_unit_id": "u2",
                        "target_unit_id": "u1",
                        "semantic_relation_type": "supports",
                        "quote": "The experiment supports the claim.",
                    },
                    {
                        "source_unit_id": "u3",
                        "target_unit_id": "u1",
                        "semantic_relation_type": "unclear",
                        "quote": "The text is ambiguous.",
                    },
                ]
            },
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


@pytest.mark.asyncio
async def test_relation_rebuilder_marks_unknown_relation_unresolved() -> None:
    relations, trace = await RelationExtractionService(
        _FakeGateway()
    ).rebuild_relations(
        request_id="req_relations",
        workspace_id="ws_relations",
        source_id="src_relations",
        units=[
            {"unit_id": "u1", "semantic_type": "claim", "text": "Claim"},
            {"unit_id": "u2", "semantic_type": "evidence", "text": "Evidence"},
            {"unit_id": "u3", "semantic_type": "premise", "text": "Premise"},
        ],
        chunk_text="Evidence supports the claim. The premise is ambiguous.",
        max_tokens=256,
        timeout_s=30,
        failure_mode=None,
    )

    assert trace.llm_response_id == "resp_argument_relations"
    assert relations[0]["relation_type"] == "supports"
    assert relations[0]["relation_status"] == "resolved"
    assert relations[1]["relation_type"] is None
    assert relations[1]["relation_status"] == "unresolved"
