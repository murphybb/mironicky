from __future__ import annotations

import pytest

from research_layer.services.llm_trace import LLMCallResult
from research_layer.services.relation_extraction_service import (
    RelationExtractionService,
)


class _FakeGateway:
    def __init__(self, parsed_json: dict[str, object] | None = None) -> None:
        self.kwargs: dict[str, object] = {}
        self.parsed_json = parsed_json or {
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
        }

    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        self.kwargs = kwargs
        return LLMCallResult(
            provider_backend="unit_test_backend",
            provider_model="unit_test_model",
            request_id=str(kwargs["request_id"]),
            llm_response_id="resp_argument_relations",
            usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            raw_text='{"relations":[]}',
            parsed_json=self.parsed_json,
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


@pytest.mark.asyncio
async def test_relation_rebuilder_marks_unknown_relation_unresolved() -> None:
    gateway = _FakeGateway()
    relations, trace = await RelationExtractionService(
        gateway
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


@pytest.mark.asyncio
async def test_relation_prompt_limits_output_to_explicit_edges() -> None:
    gateway = _FakeGateway()

    await RelationExtractionService(gateway).rebuild_relations(
        request_id="req_relations_budget",
        workspace_id="ws_relations_budget",
        source_id="src_relations_budget",
        units=[
            {"unit_id": "u1", "semantic_type": "claim", "text": "Claim"},
            {"unit_id": "u2", "semantic_type": "evidence", "text": "Evidence"},
        ],
        chunk_text="Evidence supports the claim.",
        max_tokens=256,
        timeout_s=30,
        failure_mode=None,
    )

    messages = gateway.kwargs["messages"]
    prompt_text = "\n".join(str(message.content) for message in messages)
    assert "at most 36" in prompt_text
    assert "explicit edges" in prompt_text


@pytest.mark.asyncio
async def test_relation_rebuilder_caps_dense_outputs() -> None:
    gateway = _FakeGateway(
        {
            "relations": [
                {
                    "source_unit_id": "u2",
                    "target_unit_id": "u1",
                    "semantic_relation_type": "supports",
                    "quote": f"Relation {index}",
                }
                for index in range(1, 45)
            ]
        }
    )

    relations, _trace = await RelationExtractionService(gateway).rebuild_relations(
        request_id="req_relations_cap",
        workspace_id="ws_relations_cap",
        source_id="src_relations_cap",
        units=[
            {"unit_id": "u1", "semantic_type": "claim", "text": "Claim"},
            {"unit_id": "u2", "semantic_type": "evidence", "text": "Evidence"},
        ],
        chunk_text="Evidence supports the claim.",
        max_tokens=256,
        timeout_s=30,
        failure_mode=None,
    )

    assert len(relations) == 36
    assert relations[-1]["quote"] == "Relation 36"
