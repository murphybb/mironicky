from __future__ import annotations

import json

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
                    "confidence_label": "EXTRACTED",
                    "confidence_score": 0.92,
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

    async def invoke_text(self, **kwargs: object) -> LLMCallResult:
        self.kwargs = kwargs
        return LLMCallResult(
            provider_backend="unit_test_backend",
            provider_model="unit_test_model",
            request_id=str(kwargs["request_id"]),
            llm_response_id="resp_argument_relations",
            usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            raw_text=json.dumps(self.parsed_json),
            parsed_json=None,
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


class _InvalidJsonThenValidGateway(_FakeGateway):
    def __init__(self) -> None:
        super().__init__(
            {
                "relations": [
                    {
                        "source_unit_id": "u2",
                        "target_unit_id": "u1",
                        "semantic_relation_type": "supports",
                        "confidence_label": "EXTRACTED",
                        "quote": "Evidence supports the claim.",
                    }
                ]
            }
        )
        self.calls = 0
        self.prompts: list[str] = []

    async def invoke_text(self, **kwargs: object) -> LLMCallResult:
        self.calls += 1
        messages = kwargs["messages"]
        self.prompts.append("\n".join(str(message.content) for message in messages))
        if self.calls == 1:
            return LLMCallResult(
                provider_backend="unit_test_backend",
                provider_model="unit_test_model",
                request_id=str(kwargs["request_id"]),
                llm_response_id="resp_malformed_argument_relations",
                usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
                raw_text='{"relations":[{"quote":"unterminated"}',
                parsed_json=None,
                fallback_used=False,
                degraded=False,
                degraded_reason=None,
            )
        return await super().invoke_text(**kwargs)


class _NumericTypoGateway(_FakeGateway):
    async def invoke_text(self, **kwargs: object) -> LLMCallResult:
        self.kwargs = kwargs
        return LLMCallResult(
            provider_backend="unit_test_backend",
            provider_model="unit_test_model",
            request_id=str(kwargs["request_id"]),
            llm_response_id="resp_argument_relations_typo",
            usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            raw_text=(
                '{"relations":[{"source_unit_id":"u2","target_unit_id":"u1",'
                '"semantic_relation_type":"supports","confidence_label":"EXTRACTED",'
                '"confidence_score":0.93","quote":"Evidence supports the claim."}]}'
            ),
            parsed_json=None,
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


@pytest.mark.asyncio
async def test_relation_rebuilder_marks_unknown_relation_unresolved() -> None:
    gateway = _FakeGateway()
    relations, trace = await RelationExtractionService(gateway).rebuild_relations(
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
    assert relations[0]["confidence_label"] == "EXTRACTED"
    assert relations[0]["confidence_score"] == 0.92
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
    assert "EXTRACTED" in prompt_text
    assert "INFERRED" in prompt_text


@pytest.mark.asyncio
async def test_relation_rebuilder_retries_once_on_invalid_json() -> None:
    gateway = _InvalidJsonThenValidGateway()

    relations, _trace = await RelationExtractionService(gateway).rebuild_relations(
        request_id="req_relations_retry",
        workspace_id="ws_relations_retry",
        source_id="src_relations_retry",
        units=[
            {"unit_id": "u1", "semantic_type": "claim", "text": "Claim"},
            {"unit_id": "u2", "semantic_type": "evidence", "text": "Evidence"},
        ],
        chunk_text="Evidence supports the claim.",
        max_tokens=12000,
        timeout_s=30,
        failure_mode=None,
    )

    assert gateway.calls == 2
    assert "previous answer was rejected" in gateway.prompts[1]
    assert "Return at most 12 relations" in gateway.prompts[1]
    assert relations[0]["relation_type"] == "supports"


@pytest.mark.asyncio
async def test_relation_rebuilder_repairs_numeric_confidence_typo() -> None:
    gateway = _NumericTypoGateway()

    relations, trace = await RelationExtractionService(gateway).rebuild_relations(
        request_id="req_relations_numeric_typo",
        workspace_id="ws_relations_numeric_typo",
        source_id="src_relations_numeric_typo",
        units=[
            {"unit_id": "u1", "semantic_type": "claim", "text": "Claim"},
            {"unit_id": "u2", "semantic_type": "evidence", "text": "Evidence"},
        ],
        chunk_text="Evidence supports the claim.",
        max_tokens=12000,
        timeout_s=30,
        failure_mode=None,
    )

    assert trace.degraded is True
    assert trace.degraded_reason == "research.llm_json_repaired"
    assert relations[0]["confidence_score"] == 0.93
    assert relations[0]["relation_type"] == "supports"


@pytest.mark.asyncio
async def test_relation_rebuilder_keeps_inferred_relations_unresolved() -> None:
    gateway = _FakeGateway(
        {
            "relations": [
                {
                    "source_unit_id": "u2",
                    "target_unit_id": "u1",
                    "semantic_relation_type": "defines",
                    "confidence_label": "INFERRED",
                    "confidence_score": "0.61",
                    "quote": "The construct is described near the hypothesis.",
                }
            ]
        }
    )

    relations, _trace = await RelationExtractionService(gateway).rebuild_relations(
        request_id="req_relations_inferred",
        workspace_id="ws_relations_inferred",
        source_id="src_relations_inferred",
        units=[
            {"unit_id": "u1", "semantic_type": "concept", "text": "Concept"},
            {"unit_id": "u2", "semantic_type": "definition", "text": "Definition"},
        ],
        chunk_text="The construct is described near the hypothesis.",
        max_tokens=256,
        timeout_s=30,
        failure_mode=None,
    )

    assert relations[0]["relation_type"] == "supports"
    assert relations[0]["relation_status"] == "unresolved"
    assert relations[0]["confidence_label"] == "INFERRED"
    assert relations[0]["confidence_score"] == 0.61


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
