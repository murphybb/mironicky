from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.routing.candidate_builder import RouteCandidateBuilder
from research_layer.routing.ranker import RouteRanker
from research_layer.routing.summarizer import RouteSummarizer


def _build_store(tmp_path) -> ResearchApiStateStore:
    db_path = tmp_path / "slice7_route_engine.sqlite3"
    return ResearchApiStateStore(db_path=str(db_path))


def _seed_graph_for_routes(
    store: ResearchApiStateStore, workspace_id: str
) -> tuple[list[dict[str, object]], list[dict[str, object]], str]:
    graph_nodes = [
        {
            "node_id": "node_evidence",
            "workspace_id": workspace_id,
            "node_type": "evidence",
            "object_ref_type": "evidence",
            "object_ref_id": "evi_1",
            "short_label": "Evidence node",
            "status": "active",
        },
        {
            "node_id": "node_assumption",
            "workspace_id": workspace_id,
            "node_type": "assumption",
            "object_ref_type": "assumption",
            "object_ref_id": "asm_1",
            "short_label": "Assumption node",
            "status": "active",
        },
        {
            "node_id": "node_validation",
            "workspace_id": workspace_id,
            "node_type": "validation",
            "object_ref_type": "validation",
            "object_ref_id": "val_1",
            "short_label": "Validation node",
            "status": "active",
        },
        {
            "node_id": "node_failure",
            "workspace_id": workspace_id,
            "node_type": "failure",
            "object_ref_type": "failure",
            "object_ref_id": "fail_1",
            "short_label": "Failure node",
            "status": "failed",
        },
    ]
    graph_edges = [
        {
            "edge_id": "edge_1",
            "workspace_id": workspace_id,
            "source_node_id": "node_evidence",
            "target_node_id": "node_assumption",
            "edge_type": "supports",
            "object_ref_type": "evidence",
            "object_ref_id": "evi_1",
            "strength": 0.8,
            "status": "active",
        },
        {
            "edge_id": "edge_2",
            "workspace_id": workspace_id,
            "source_node_id": "node_assumption",
            "target_node_id": "node_validation",
            "edge_type": "requires_validation",
            "object_ref_type": "validation",
            "object_ref_id": "val_1",
            "strength": 0.7,
            "status": "active",
        },
        {
            "edge_id": "edge_3",
            "workspace_id": workspace_id,
            "source_node_id": "node_evidence",
            "target_node_id": "node_failure",
            "edge_type": "conflicted_by",
            "object_ref_type": "failure",
            "object_ref_id": "fail_1",
            "strength": 0.9,
            "status": "active",
        },
    ]
    return graph_nodes, graph_edges, "ver_slice7_static_1"


def test_slice7_candidate_builder_creates_multiple_traceable_candidates(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice7_builder"
    graph_nodes, graph_edges, version_id = _seed_graph_for_routes(store, workspace_id)

    builder = RouteCandidateBuilder()
    candidates = builder.build_candidates(
        workspace_id=workspace_id,
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
        version_id=version_id,
        max_candidates=8,
    )

    assert len(candidates) >= 2
    for candidate in candidates:
        assert candidate["conclusion_node_id"]
        assert candidate["conclusion_node_id"] in candidate["route_node_ids"]
        assert candidate["trace_refs"]["version_id"] == version_id
        assert candidate["trace_refs"]["route_node_ids"]
        assert isinstance(candidate["trace_refs"].get("route_edge_ids"), list)


def test_slice7_candidate_builder_prefers_claim_nodes_over_evidence_titles() -> None:
    builder = RouteCandidateBuilder()
    candidates = builder.build_candidates(
        workspace_id="ws_slice7_claim_priority",
        graph_nodes=[
            {
                "node_id": "node_evidence",
                "workspace_id": "ws_slice7_claim_priority",
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evi_1",
                "short_label": "Evidence node",
                "status": "active",
                "short_tags": ["result"],
            },
            {
                "node_id": "node_claim",
                "workspace_id": "ws_slice7_claim_priority",
                "node_type": "assumption",
                "object_ref_type": "assumption",
                "object_ref_id": "asm_1",
                "short_label": "Hypothesis node",
                "status": "active",
                "short_tags": ["hypothesis"],
            },
        ],
        graph_edges=[
            {
                "edge_id": "edge_support",
                "workspace_id": "ws_slice7_claim_priority",
                "source_node_id": "node_evidence",
                "target_node_id": "node_claim",
                "edge_type": "supports",
                "object_ref_type": "relation_candidate",
                "object_ref_id": "rel_1",
                "strength": 0.8,
                "status": "active",
            }
        ],
        version_id="ver_claim_priority",
        max_candidates=8,
    )

    assert [candidate["conclusion_node_id"] for candidate in candidates] == ["node_claim"]


def test_slice7_candidate_builder_ignores_superseded_graph_objects() -> None:
    builder = RouteCandidateBuilder()
    candidates = builder.build_candidates(
        workspace_id="ws_slice7_superseded",
        graph_nodes=[
            {
                "node_id": "node_old_claim",
                "workspace_id": "ws_slice7_superseded",
                "node_type": "assumption",
                "object_ref_type": "assumption",
                "object_ref_id": "asm_old",
                "short_label": "Old claim",
                "status": "superseded",
            },
            {
                "node_id": "node_new_claim",
                "workspace_id": "ws_slice7_superseded",
                "node_type": "assumption",
                "object_ref_type": "assumption",
                "object_ref_id": "asm_new",
                "short_label": "New claim",
                "status": "active",
            },
            {
                "node_id": "node_new_evidence",
                "workspace_id": "ws_slice7_superseded",
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evi_new",
                "short_label": "New evidence",
                "status": "active",
            },
        ],
        graph_edges=[
            {
                "edge_id": "edge_old",
                "workspace_id": "ws_slice7_superseded",
                "source_node_id": "node_old_claim",
                "target_node_id": "node_new_claim",
                "edge_type": "supports",
                "object_ref_type": "relation_candidate",
                "object_ref_id": "rel_old",
                "strength": 0.8,
                "status": "superseded",
            },
            {
                "edge_id": "edge_new",
                "workspace_id": "ws_slice7_superseded",
                "source_node_id": "node_new_evidence",
                "target_node_id": "node_new_claim",
                "edge_type": "supports",
                "object_ref_type": "relation_candidate",
                "object_ref_id": "rel_new",
                "strength": 0.8,
                "status": "active",
            },
        ],
        version_id="ver_superseded",
        max_candidates=8,
    )

    assert len(candidates) == 1
    assert candidates[0]["conclusion_node_id"] == "node_new_claim"
    assert set(candidates[0]["route_node_ids"]) == {"node_new_claim", "node_new_evidence"}
    assert candidates[0]["trace_refs"]["route_edge_ids"] == ["edge_new"]


def test_slice7_candidate_builder_uses_risk_nodes_as_last_resort() -> None:
    builder = RouteCandidateBuilder()
    candidates = builder.build_candidates(
        workspace_id="ws_slice7_risk_only",
        graph_nodes=[
            {
                "node_id": "node_conflict",
                "workspace_id": "ws_slice7_risk_only",
                "node_type": "conflict",
                "object_ref_type": "conflict",
                "object_ref_id": "conf_1",
                "short_label": "Conflict node",
                "status": "active",
            },
            {
                "node_id": "node_failure",
                "workspace_id": "ws_slice7_risk_only",
                "node_type": "failure",
                "object_ref_type": "failure",
                "object_ref_id": "fail_1",
                "short_label": "Failure node",
                "status": "active",
            },
        ],
        graph_edges=[
            {
                "edge_id": "edge_risk_1",
                "workspace_id": "ws_slice7_risk_only",
                "source_node_id": "node_conflict",
                "target_node_id": "node_failure",
                "edge_type": "conflicts",
                "object_ref_type": "conflict",
                "object_ref_id": "conf_1",
                "strength": 0.7,
                "status": "active",
            }
        ],
        version_id="ver_risk_only",
        max_candidates=8,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["conclusion_node_id"] in {"node_conflict", "node_failure"}
    assert set(candidate["route_node_ids"]) == {"node_conflict", "node_failure"}
    assert set(candidate["risk_node_ids"]) == {"node_conflict", "node_failure"}


def test_slice7_ranker_uses_programmatic_sort_and_stable_tie_break() -> None:
    ranker = RouteRanker()
    routes = [
        {
            "route_id": "route_b",
            "support_score": 70.0,
            "risk_score": 30.0,
            "progressability_score": 60.0,
            "summary": "text that should not affect rank",
            "score_breakdown": {
                "risk_score": {
                    "factors": [
                        {
                            "factor_name": "private_dependency_pressure",
                            "normalized_value": 0.3,
                        }
                    ]
                }
            },
        },
        {
            "route_id": "route_a",
            "support_score": 70.0,
            "risk_score": 30.0,
            "progressability_score": 60.0,
            "summary": "another text",
            "score_breakdown": {
                "risk_score": {
                    "factors": [
                        {
                            "factor_name": "private_dependency_pressure",
                            "normalized_value": 0.1,
                        }
                    ]
                }
            },
        },
        {
            "route_id": "route_c",
            "support_score": 71.0,
            "risk_score": 40.0,
            "progressability_score": 20.0,
            "summary": "higher support should not win when confidence is lower",
            "score_breakdown": {
                "risk_score": {
                    "factors": [
                        {
                            "factor_name": "private_dependency_pressure",
                            "normalized_value": 0.9,
                        }
                    ]
                }
            },
        },
    ]

    ranked = ranker.rank_routes(routes)
    assert [route["route_id"] for route in ranked] == ["route_a", "route_b", "route_c"]


def test_route_summary_prompt_contract_is_owned_by_pr_e() -> None:
    prompt_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "research_layer"
        / "prompts"
        / "route_summary.txt"
    )
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "Output schema (strict)" in prompt
    assert '{"summary"' in prompt or '"summary"' in prompt
    assert '"key_strengths"' in prompt
    assert '"key_risks"' in prompt
    assert '"open_questions"' in prompt
    assert '"node_refs"' in prompt
    assert "{route_id}" in prompt
    assert "{conclusion_node_json}" in prompt
    assert "{all_route_nodes_json}" in prompt
    assert "Do not fabricate" in prompt
    assert "Do not modify any ranking or score" in prompt


@pytest.mark.asyncio
async def test_slice7_summarizer_returns_structured_llm_summary(monkeypatch) -> None:
    summarizer = RouteSummarizer()

    class _FakeGateway:
        async def invoke_json(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(
                provider_backend="openai_compatible",
                provider_model="gpt-4.1-mini",
                request_id="req_slice7_summary",
                llm_response_id="resp_slice7_summary",
                usage={"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50},
                raw_text="{}",
                parsed_json={
                    "summary": "Route is support-strong but needs targeted validation.",
                    "key_strengths": [
                        {"text": "Evidence is directly relevant", "node_refs": ["node_support"]}
                    ],
                    "key_risks": [
                        {"text": "Latency risk remains", "node_refs": ["node_failure"]}
                    ],
                    "open_questions": [
                        {"text": "Will queue control stabilize p95?", "node_refs": ["node_validation"]}
                    ],
                },
                fallback_used=False,
                degraded=False,
                degraded_reason=None,
            )

    monkeypatch.setattr(summarizer, "_gateway", _FakeGateway())

    candidate = {
        "conclusion_node_id": "node_conclusion",
        "route_node_ids": [
            "node_conclusion",
            "node_support",
            "node_assumption",
            "node_failure",
            "node_validation",
        ],
        "key_support_node_ids": ["node_support"],
        "key_assumption_node_ids": ["node_assumption"],
        "risk_node_ids": ["node_failure"],
        "next_validation_node_id": "node_validation",
        "next_validation_action": "run ablation on retrieval settings",
        "trace_refs": {
            "version_id": "ver_1",
            "route_node_ids": ["node_conclusion", "node_support"],
            "route_edge_ids": ["edge_1", "edge_2"],
        },
    }
    node_map = {
        "node_conclusion": {
            "node_id": "node_conclusion",
            "node_type": "evidence",
            "object_ref_type": "evidence",
            "object_ref_id": "evi_1",
            "short_label": "Conclusion evidence",
            "status": "active",
        },
        "node_support": {
            "node_id": "node_support",
            "node_type": "evidence",
            "object_ref_type": "evidence",
            "object_ref_id": "evi_2",
            "short_label": "Support evidence",
            "status": "active",
        },
        "node_assumption": {
            "node_id": "node_assumption",
            "node_type": "assumption",
            "object_ref_type": "assumption",
            "object_ref_id": "asm_1",
            "short_label": "Assumption",
            "status": "active",
        },
        "node_failure": {
            "node_id": "node_failure",
            "node_type": "failure",
            "object_ref_type": "failure",
            "object_ref_id": "fail_1",
            "short_label": "Failure",
            "status": "failed",
        },
        "node_validation": {
            "node_id": "node_validation",
            "node_type": "validation",
            "object_ref_type": "validation",
            "object_ref_id": "val_1",
            "short_label": "Validation",
            "status": "active",
        },
    }

    summary, trace = await summarizer.summarize(
        candidate=candidate,
        node_map=node_map,
        top_factors=[],
        request_id="req_slice7_summary",
        allow_fallback=False,
    )

    assert summary["summary_generation_mode"] == "llm"
    assert summary["degraded"] is False
    assert summary["fallback_used"] is False
    assert summary["summary"]
    assert summary["key_strengths"]
    assert summary["key_risks"]
    assert summary["open_questions"]
    assert summary["trace_refs"]["route_edge_ids"] == ["edge_1", "edge_2"]
    assert trace.provider_backend == "openai_compatible"


@pytest.mark.asyncio
async def test_slice7_summarizer_default_llm_timeout_is_five_minutes(monkeypatch) -> None:
    monkeypatch.delenv("RESEARCH_ROUTE_SUMMARY_LLM_TIMEOUT_SECONDS", raising=False)
    summarizer = RouteSummarizer()
    calls: list[dict[str, object]] = []

    class _FakeGateway:
        async def invoke_json(self, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(
                provider_backend="openai_compatible",
                provider_model="gpt-4.1-mini",
                request_id="req_slice7_timeout",
                llm_response_id="resp_slice7_timeout",
                usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                raw_text="{}",
                parsed_json={
                    "summary": "summary text",
                    "key_strengths": [{"text": "strength", "node_refs": ["node_conclusion"]}],
                    "key_risks": [],
                    "open_questions": [],
                },
                fallback_used=False,
                degraded=False,
                degraded_reason=None,
            )

    monkeypatch.setattr(summarizer, "_gateway", _FakeGateway())

    summary, _trace = await summarizer.summarize(
        candidate={
            "conclusion_node_id": "node_conclusion",
            "route_node_ids": ["node_conclusion"],
            "key_support_node_ids": ["node_conclusion"],
            "key_assumption_node_ids": [],
            "risk_node_ids": [],
            "next_validation_action": "validate",
            "trace_refs": {"version_id": "ver_1", "route_edge_ids": []},
        },
        node_map={
            "node_conclusion": {
                "node_id": "node_conclusion",
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evi_1",
                "short_label": "Conclusion evidence",
                "status": "active",
            }
        },
        top_factors=[],
        request_id="req_slice7_timeout",
        allow_fallback=False,
    )

    assert summary["summary_generation_mode"] == "llm"
    assert calls
    assert calls[0]["timeout_s"] == 300.0


@pytest.mark.asyncio
async def test_slice7_summarizer_fallback_is_explicit(monkeypatch) -> None:
    summarizer = RouteSummarizer()

    class _FailingGateway:
        async def invoke_json(self, **_: object) -> SimpleNamespace:
            from research_layer.services.llm_gateway import ResearchLLMError

            raise ResearchLLMError(
                status_code=504,
                error_code="research.llm_timeout",
                message="timeout",
                details={},
            )

    monkeypatch.setattr(summarizer, "_gateway", _FailingGateway())

    summary, trace = await summarizer.summarize(
        candidate={
            "conclusion_node_id": "node_conclusion",
            "route_node_ids": ["node_conclusion"],
            "key_support_node_ids": [],
            "key_assumption_node_ids": [],
            "risk_node_ids": [],
            "next_validation_action": "validate",
            "trace_refs": {"version_id": "ver_1", "route_edge_ids": []},
        },
        node_map={
            "node_conclusion": {
                "node_id": "node_conclusion",
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evi_1",
                "short_label": "Conclusion evidence",
                "status": "active",
            }
        },
        top_factors=[],
        request_id="req_slice7_summary_fallback",
        allow_fallback=True,
    )

    assert summary["summary_generation_mode"] == "degraded_fallback"
    assert summary["degraded"] is True
    assert summary["fallback_used"] is True
    assert summary["degraded_reason"] == "research.llm_timeout"
    assert isinstance(summary["key_strengths"], list)
    assert isinstance(summary["key_risks"], list)
    assert isinstance(summary["open_questions"], list)
    assert trace.fallback_used is True


@pytest.mark.asyncio
async def test_slice7_summarizer_filters_unknown_node_refs(monkeypatch) -> None:
    summarizer = RouteSummarizer()

    class _FakeGateway:
        async def invoke_json(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(
                provider_backend="openai_compatible",
                provider_model="gpt-4.1-mini",
                request_id="req_slice7_unknown_refs",
                llm_response_id="resp_slice7_unknown_refs",
                usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                raw_text="{}",
                parsed_json={
                    "summary": "summary text",
                    "key_strengths": [
                        {"text": "invalid ref", "node_refs": ["node_not_in_route"]}
                    ],
                    "key_risks": [],
                    "open_questions": [],
                },
                fallback_used=False,
                degraded=False,
                degraded_reason=None,
            )

    monkeypatch.setattr(summarizer, "_gateway", _FakeGateway())
    candidate = {
        "conclusion_node_id": "node_conclusion",
        "route_node_ids": ["node_conclusion", "node_support"],
        "key_support_node_ids": ["node_support"],
        "key_assumption_node_ids": [],
        "risk_node_ids": [],
        "next_validation_action": "validate",
        "trace_refs": {"version_id": "ver_1", "route_edge_ids": []},
    }
    node_map = {
        "node_conclusion": {
            "node_id": "node_conclusion",
            "node_type": "evidence",
            "object_ref_type": "evidence",
            "object_ref_id": "evi_1",
            "short_label": "Conclusion evidence",
            "status": "active",
        },
        "node_support": {
            "node_id": "node_support",
            "node_type": "evidence",
            "object_ref_type": "evidence",
            "object_ref_id": "evi_2",
            "short_label": "Support evidence",
            "status": "active",
        },
    }

    summary, _trace = await summarizer.summarize(
        candidate=candidate,
        node_map=node_map,
        top_factors=[],
        request_id="req_slice7_unknown_refs",
        allow_fallback=False,
    )

    assert summary["key_strengths"] == [{"text": "invalid ref", "node_refs": []}]


def test_route_edge_ids_json_is_persisted_as_canonical_source(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_route_edge_persist"

    route = store.create_route(
        workspace_id=workspace_id,
        title="route title",
        summary="route summary",
        status="candidate",
        support_score=0.0,
        risk_score=0.0,
        progressability_score=0.0,
        conclusion="conclusion",
        key_supports=[],
        assumptions=[],
        risks=[],
        next_validation_action="validate",
        route_node_ids=["node_a", "node_b"],
        route_edge_ids=["edge_a", "edge_b"],
        version_id="ver_1",
    )

    loaded = store.get_route(str(route["route_id"]))
    assert loaded is not None
    assert loaded["route_edge_ids"] == ["edge_a", "edge_b"]

    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            "SELECT route_edge_ids_json FROM routes WHERE route_id = ?",
            (str(route["route_id"]),),
        ).fetchone()
    assert row is not None
    assert json.loads(str(row[0])) == ["edge_a", "edge_b"]
