from __future__ import annotations

import json

import pytest

from research_layer.services.argument_unit_extraction_service import (
    ArgumentUnitExtractionService,
)
from research_layer.services.llm_trace import LLMCallResult
from research_layer.services import prompt_renderer


class _FakeGateway:
    def __init__(self, parsed_json: dict[str, object] | None = None) -> None:
        self.kwargs: dict[str, object] = {}
        self.parsed_json = parsed_json or {
            "domain_profile": ["computer_science"],
            "units": [
                {
                    "unit_id": "u1",
                    "semantic_type": "claim",
                    "domain_tags": ["result"],
                    "text": "The intervention improved retrieval quality.",
                    "normalized_label": "retrieval quality improved",
                    "quote": "The intervention improved retrieval quality.",
                    "confidence_score": 0.94,
                    "anchor": {"page": 1, "block_id": "p1-b0"},
                }
            ],
        }

    async def invoke_text(self, **kwargs: object) -> LLMCallResult:
        self.kwargs = kwargs
        return LLMCallResult(
            provider_backend="unit_test_backend",
            provider_model="unit_test_model",
            request_id=str(kwargs["request_id"]),
            llm_response_id="resp_argument_units",
            usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            raw_text=json.dumps(self.parsed_json),
            parsed_json=None,
            fallback_used=False,
            degraded=False,
            degraded_reason=None,
        )


def test_prompt_renderer_strips_utf8_bom(monkeypatch, tmp_path) -> None:
    prompt_path = tmp_path / "bom_prompt.txt"
    prompt_path.write_text("\ufeffSYSTEM:\nRead the paper.", encoding="utf-8")
    monkeypatch.setattr(prompt_renderer, "PROMPT_DIR", tmp_path)

    template = prompt_renderer.load_prompt_template("bom_prompt.txt")

    assert template.startswith("SYSTEM:")


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
        chunk_section="full",
        chunk_text="The intervention improved retrieval quality.",
        anchor_refs=[{"page": 1, "block_id": "p1-b0"}],
        document_reading_memo="Read as an argument graph.",
        artifact_profile={"dominant_artifact_type": "text", "artifact_counts": {"text": 1}},
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
            "normalized_label": "retrieval quality improved",
            "domain_profile": ["computer_science"],
            "domain_tags": ["result"],
            "confidence_score": 0.94,
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
        chunk_section="3.1 Method",
        chunk_text="The report contains many repeated observations.",
        anchor_refs=[],
        document_reading_memo="Read as an argument graph.",
        artifact_profile={"dominant_artifact_type": "text", "artifact_counts": {"text": 1}},
        max_tokens=256,
        timeout_s=30,
        failure_mode=None,
    )

    messages = gateway.kwargs["messages"]
    prompt_text = "\n".join(str(message.content) for message in messages)
    assert "at most 32" in prompt_text
    assert "core knowledge units" in prompt_text
    assert "PaperMap" in prompt_text
    assert "route_seed_candidates" in prompt_text
    assert "domain_profile" in prompt_text
    assert "hypothesis" in prompt_text
    assert "artifact_profile_json" in prompt_text
    assert "statistical_test" in prompt_text
    assert "equation" in prompt_text
    assert "code" in prompt_text


@pytest.mark.asyncio
async def test_argument_unit_extractor_accepts_universal_scholarly_types() -> None:
    gateway = _FakeGateway(
        {
            "domain_profile": ["social_science", "business"],
            "units": [
                {
                    "unit_id": "u1",
                    "semantic_type": "hypothesis",
                    "domain_tags": ["hypothesis", "mediator"],
                    "text": "Social mainstream consistency mediates brand attitude.",
                    "quote": "Social mainstream consistency mediates brand attitude.",
                    "confidence_score": "0.88",
                    "anchor": {},
                },
                {
                    "unit_id": "u2",
                    "semantic_type": "method",
                    "domain_tags": ["measurement"],
                    "text": "The study uses questionnaire data.",
                    "quote": "The study uses questionnaire data.",
                    "confidence_score": 1.2,
                    "anchor": {},
                },
            ],
        }
    )

    units, _trace = await ArgumentUnitExtractionService(gateway).extract_units(
        request_id="req_units_universal",
        workspace_id="ws_units_universal",
        source_id="src_units_universal",
        source_title="Source",
        source_type="paper",
        chunk_id="chunk_src_units_universal",
        chunk_section="2.1 Hypotheses",
        chunk_text="Social mainstream consistency mediates brand attitude.",
        anchor_refs=[],
        document_reading_memo="Read as a scholarly graph.",
        artifact_profile={"dominant_artifact_type": "text", "artifact_counts": {"text": 1}},
        max_tokens=256,
        timeout_s=30,
        failure_mode=None,
    )

    assert units[0]["semantic_type"] == "hypothesis"
    assert units[0]["candidate_type"] == "assumption"
    assert units[0]["domain_profile"] == ["social_science", "business"]
    assert units[0]["domain_tags"] == ["hypothesis", "mediator"]
    assert units[0]["confidence_score"] == 0.88
    assert units[1]["semantic_type"] == "method"
    assert units[1]["candidate_type"] == "evidence"
    assert units[1]["confidence_score"] == 1.0


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
                for index in range(1, 41)
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
        chunk_section="full",
        chunk_text="Many repeated claims.",
        anchor_refs=[],
        document_reading_memo="Read as an argument graph.",
        artifact_profile={"dominant_artifact_type": "text", "artifact_counts": {"text": 1}},
        max_tokens=256,
        timeout_s=30,
        failure_mode=None,
    )

    assert len(units) == 32
    assert units[-1]["unit_id"] == "u32"


@pytest.mark.asyncio
async def test_argument_unit_extractor_accepts_artifact_specific_schema_types() -> None:
    gateway = _FakeGateway(
        {
            "domain_profile": ["mathematics", "computer_science"],
            "units": [
                {
                    "unit_id": "u1",
                    "semantic_type": "equation",
                    "domain_tags": ["equation"],
                    "text": "The update rule is x_{t+1}=x_t-η∇L(x_t).",
                    "quote": "x_{t+1}=x_t-η∇L(x_t)",
                    "confidence_score": 0.9,
                    "anchor": {},
                },
                {
                    "unit_id": "u2",
                    "semantic_type": "dataset",
                    "domain_tags": ["dataset"],
                    "text": "The model is evaluated on CIFAR-10.",
                    "quote": "evaluated on CIFAR-10",
                    "confidence_score": 0.8,
                    "anchor": {},
                },
                {
                    "unit_id": "u3",
                    "semantic_type": "code",
                    "domain_tags": ["code"],
                    "text": "The pseudocode iterates until convergence.",
                    "quote": "iterates until convergence",
                    "confidence_score": 0.7,
                    "anchor": {},
                },
            ],
        }
    )

    units, _trace = await ArgumentUnitExtractionService(gateway).extract_units(
        request_id="req_units_artifacts",
        workspace_id="ws_units_artifacts",
        source_id="src_units_artifacts",
        source_title="Source",
        source_type="paper",
        chunk_id="chunk_src_units_artifacts",
        chunk_section="Appendix A",
        chunk_text="x_{t+1}=x_t-η∇L(x_t). The model is evaluated on CIFAR-10.",
        anchor_refs=[],
        document_reading_memo="Read as a scholarly graph.",
        artifact_profile={"dominant_artifact_type": "formula", "artifact_counts": {"formula": 1, "code": 1}},
        max_tokens=256,
        timeout_s=30,
        failure_mode=None,
    )

    assert [unit["candidate_type"] for unit in units] == [
        "evidence",
        "evidence",
        "evidence",
    ]
    assert [unit["semantic_type"] for unit in units] == [
        "equation",
        "dataset",
        "code",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("artifact_profile", "expected_phrase"),
    [
        (
            {"dominant_artifact_type": "table", "artifact_counts": {"table": 1}},
            "structured table block",
        ),
        (
            {"dominant_artifact_type": "formula", "artifact_counts": {"formula": 1}},
            "formula or equation block",
        ),
        (
            {"dominant_artifact_type": "figure", "artifact_counts": {"figure": 1}},
            "figure caption or figure-like artifact",
        ),
        (
            {"dominant_artifact_type": "code", "artifact_counts": {"code": 1}},
            "code or pseudocode block",
        ),
    ],
)
async def test_argument_unit_extractor_uses_artifact_specific_prompts(
    artifact_profile: dict[str, object], expected_phrase: str
) -> None:
    gateway = _FakeGateway({"units": []})

    await ArgumentUnitExtractionService(gateway).extract_units(
        request_id="req_units_prompt_switch",
        workspace_id="ws_units_prompt_switch",
        source_id="src_units_prompt_switch",
        source_title="Source",
        source_type="paper",
        chunk_id="chunk_src_units_prompt_switch",
        chunk_section="appendix",
        chunk_text="artifact content",
        anchor_refs=[],
        document_reading_memo="Read as a scholarly graph.",
        artifact_profile=artifact_profile,
        max_tokens=256,
        timeout_s=30,
        failure_mode=None,
    )

    messages = gateway.kwargs["messages"]
    prompt_text = "\n".join(str(message.content) for message in messages)
    assert expected_phrase in prompt_text
