from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.routing.candidate_builder import RouteCandidateBuilder
from research_layer.routing.ranker import RouteRanker
from research_layer.routing import summarizer as route_summarizer_module
from research_layer.routing.summarizer import RouteSummarizer
from research_layer.services.route_generation_service import RouteGenerationService


def _build_store(tmp_path) -> ResearchApiStateStore:
    db_path = tmp_path / "slice7_route_engine.sqlite3"
    return ResearchApiStateStore(db_path=str(db_path))


def test_slice7_route_summarizer_prompt_loader_strips_utf8_bom(monkeypatch, tmp_path) -> None:
    prompt_path = tmp_path / "route_summary.txt"
    prompt_path.write_text("\ufeffSYSTEM:\nSummarize the route.", encoding="utf-8")
    monkeypatch.setattr(route_summarizer_module, "_PROMPT_DIR", tmp_path)

    template = route_summarizer_module._load_prompt_template("route_summary.txt")

    assert template.startswith("SYSTEM:")


class _FakeRouteGenerationStore:
    def __init__(self) -> None:
        self.routes: dict[str, dict[str, object]] = {}

    def list_graph_nodes(self, workspace_id: str) -> list[dict[str, object]]:
        return [
            {
                "node_id": "node_claim",
                "workspace_id": workspace_id,
                "node_type": "conclusion",
                "object_ref_type": "claim",
                "object_ref_id": "claim_1",
                "short_label": "Central claim",
                "status": "active",
            },
            {
                "node_id": "node_support",
                "workspace_id": workspace_id,
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evidence_1",
                "short_label": "Support evidence",
                "status": "active",
            },
        ]

    def list_graph_edges(self, workspace_id: str) -> list[dict[str, object]]:
        return [
            {
                "edge_id": "edge_supports",
                "workspace_id": workspace_id,
                "source_node_id": "node_support",
                "target_node_id": "node_claim",
                "edge_type": "supports",
                "status": "active",
            }
        ]

    def get_graph_workspace(self, workspace_id: str) -> dict[str, object]:
        return {"workspace_id": workspace_id, "latest_version_id": "ver_1"}

    def emit_event(self, **_: object) -> None:
        return None

    def list_routes(self, workspace_id: str) -> list[dict[str, object]]:
        return []

    def create_route(self, **kwargs: object) -> dict[str, object]:
        route_id = f"route_{len(self.routes) + 1}"
        route = {"route_id": route_id, **kwargs}
        self.routes[route_id] = route
        return route

    def update_route_projection(self, route_id: str, **kwargs: object) -> dict[str, object]:
        route = {**self.routes[route_id], **kwargs}
        self.routes[route_id] = route
        return route

    def update_route_rank(self, route_id: str, rank: int) -> dict[str, object]:
        route = {**self.routes[route_id], "rank": rank}
        self.routes[route_id] = route
        return route

    def delete_route(self, route_id: str) -> None:
        self.routes.pop(route_id, None)


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


@pytest.mark.asyncio
async def test_route_generation_summarizes_each_candidate_once() -> None:
    service = RouteGenerationService(_FakeRouteGenerationStore())  # type: ignore[arg-type]

    candidate = {
        "conclusion_node_id": "node_claim",
        "route_node_ids": ["node_claim", "node_support"],
        "key_support_node_ids": ["node_support"],
        "key_assumption_node_ids": [],
        "risk_node_ids": [],
        "next_validation_action": "validate the claim",
        "trace_refs": {
            "version_id": "ver_1",
            "route_node_ids": ["node_claim", "node_support"],
            "route_edge_ids": ["edge_supports"],
        },
    }

    class _FakeBuilder:
        def build_candidates(self, **_: object) -> list[dict[str, object]]:
            return [candidate]

    class _FakeScoreService:
        def score_route(self, **_: object) -> dict[str, object]:
            return {"top_factors": [{"factor_name": "support"}]}

    class _FakeSummarizer:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def summarize(
            self, **kwargs: object
        ) -> tuple[dict[str, object], SimpleNamespace]:
            self.calls.append(kwargs)
            return (
                {
                    "title": "Central claim route",
                    "summary": "Evidence supports the central claim.",
                    "conclusion": "Central claim",
                    "key_supports": ["Support evidence"],
                    "assumptions": [],
                    "risks": [],
                    "next_validation_action": "validate the claim",
                    "summary_generation_mode": "llm",
                    "key_strengths": [],
                    "key_risks": [],
                    "open_questions": [],
                    "degraded": False,
                    "fallback_used": False,
                    "degraded_reason": None,
                },
                SimpleNamespace(
                    provider_backend="unit_test_backend",
                    provider_model="unit_test_model",
                    request_id="req_route_once",
                    llm_response_id="resp_route_once",
                    usage={
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
                    fallback_used=False,
                    degraded=False,
                    degraded_reason=None,
                ),
            )

    summarizer = _FakeSummarizer()
    service._builder = _FakeBuilder()  # type: ignore[assignment]
    service._score_service = _FakeScoreService()  # type: ignore[assignment]
    service._summarizer = summarizer  # type: ignore[assignment]

    result = await service.generate_routes(
        workspace_id="ws_route_once",
        request_id="req_route_once",
        reason="unit test",
        max_candidates=1,
        allow_fallback=False,
    )

    assert result["generated_count"] == 1
    assert len(summarizer.calls) == 1
    assert summarizer.calls[0]["top_factors"] == [{"factor_name": "support"}]

@pytest.mark.asyncio
async def test_route_generation_summarizes_candidates_concurrently(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RESEARCH_ROUTE_SUMMARY_CONCURRENCY", "2")
    service = RouteGenerationService(_FakeRouteGenerationStore())  # type: ignore[arg-type]

    candidates = [
        {
            "conclusion_node_id": "node_claim",
            "route_node_ids": ["node_claim", "node_support"],
            "key_support_node_ids": ["node_support"],
            "key_assumption_node_ids": [],
            "risk_node_ids": [],
            "next_validation_action": "validate the claim",
            "trace_refs": {
                "version_id": "ver_1",
                "route_node_ids": ["node_claim", "node_support"],
                "route_edge_ids": ["edge_supports"],
            },
        },
        {
            "conclusion_node_id": "node_claim",
            "route_node_ids": ["node_claim", "node_support"],
            "key_support_node_ids": ["node_support"],
            "key_assumption_node_ids": [],
            "risk_node_ids": [],
            "next_validation_action": "replicate the claim",
            "trace_refs": {
                "version_id": "ver_1",
                "route_node_ids": ["node_claim", "node_support"],
                "route_edge_ids": ["edge_supports"],
            },
        },
    ]

    class _FakeBuilder:
        def build_candidates(self, **_: object) -> list[dict[str, object]]:
            return candidates

    class _FakeScoreService:
        def score_route(self, **_: object) -> dict[str, object]:
            return {"top_factors": [{"factor_name": "support"}]}

    class _SlowSummarizer:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0

        async def summarize(
            self, **kwargs: object
        ) -> tuple[dict[str, object], SimpleNamespace]:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            candidate = kwargs["candidate"]
            assert isinstance(candidate, dict)
            return (
                {
                    "title": f"Route for {candidate['next_validation_action']}",
                    "summary": "Evidence supports the central claim.",
                    "conclusion": "Central claim",
                    "key_supports": ["Support evidence"],
                    "assumptions": [],
                    "risks": [],
                    "next_validation_action": str(candidate["next_validation_action"]),
                    "summary_generation_mode": "llm",
                    "key_strengths": [],
                    "key_risks": [],
                    "open_questions": [],
                    "degraded": False,
                    "fallback_used": False,
                    "degraded_reason": None,
                },
                SimpleNamespace(
                    provider_backend="unit_test_backend",
                    provider_model="unit_test_model",
                    request_id="req_route_parallel",
                    llm_response_id="resp_route_parallel",
                    usage={},
                    fallback_used=False,
                    degraded=False,
                    degraded_reason=None,
                ),
            )

    summarizer = _SlowSummarizer()
    service._builder = _FakeBuilder()  # type: ignore[assignment]
    service._score_service = _FakeScoreService()  # type: ignore[assignment]
    service._summarizer = summarizer  # type: ignore[assignment]

    result = await service.generate_routes(
        workspace_id="ws_route_parallel",
        request_id="req_route_parallel",
        reason="unit test",
        max_candidates=2,
        allow_fallback=False,
    )

    assert result["generated_count"] == 2
    assert summarizer.max_active == 2


@pytest.mark.asyncio
async def test_route_generation_cleans_pending_routes_when_cancelled() -> None:
    store = _FakeRouteGenerationStore()
    service = RouteGenerationService(store)  # type: ignore[arg-type]

    class _FakeBuilder:
        def build_candidates(self, **_: object) -> list[dict[str, object]]:
            return [
                {
                    "conclusion_node_id": "node_claim",
                    "route_node_ids": ["node_claim", "node_support"],
                    "key_support_node_ids": ["node_support"],
                    "key_assumption_node_ids": [],
                    "risk_node_ids": [],
                    "next_validation_action": "validate the claim",
                    "trace_refs": {
                        "version_id": "ver_1",
                        "route_node_ids": ["node_claim", "node_support"],
                        "route_edge_ids": ["edge_supports"],
                    },
                }
            ]

    class _FakeScoreService:
        def score_route(self, **_: object) -> dict[str, object]:
            return {"top_factors": [{"factor_name": "support"}]}

    class _CancellingSummarizer:
        async def summarize(self, **_: object) -> tuple[dict[str, object], object]:
            raise asyncio.CancelledError()

    service._builder = _FakeBuilder()  # type: ignore[assignment]
    service._score_service = _FakeScoreService()  # type: ignore[assignment]
    service._summarizer = _CancellingSummarizer()  # type: ignore[assignment]

    with pytest.raises(asyncio.CancelledError):
        await service.generate_routes(
            workspace_id="ws_route_cancelled",
            request_id="req_route_cancelled",
            reason="unit test",
            max_candidates=1,
            allow_fallback=False,
        )

    assert store.routes == {}


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

    assert len(candidates) >= 1
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


def test_slice7_candidate_builder_uses_result_evidence_when_only_conditions_exist() -> None:
    builder = RouteCandidateBuilder()
    candidates = builder.build_candidates(
        workspace_id="ws_slice7_result_seed",
        graph_nodes=[
            {
                "node_id": "node_condition",
                "workspace_id": "ws_slice7_result_seed",
                "node_type": "assumption",
                "object_ref_type": "assumption",
                "object_ref_id": "asm_1",
                "short_label": "Operational condition",
                "status": "active",
                "short_tags": ["condition"],
                "source_ref": {"anchor_id": "p1-b0"},
            },
            {
                "node_id": "node_method",
                "workspace_id": "ws_slice7_result_seed",
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evi_1",
                "short_label": "GNN encoder and transformer processor",
                "status": "active",
                "short_tags": ["method"],
                "source_ref": {"anchor_id": "p1-b0"},
            },
            {
                "node_id": "node_dataset",
                "workspace_id": "ws_slice7_result_seed",
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evi_2",
                "short_label": "ERA5 and operational analyses",
                "status": "active",
                "short_tags": ["dataset"],
                "source_ref": {"anchor_id": "p1-b0"},
            },
            {
                "node_id": "node_result",
                "workspace_id": "ws_slice7_result_seed",
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evi_3",
                "short_label": "AIFS produces skilled forecasts",
                "status": "active",
                "short_tags": ["outcome"],
                "source_ref": {"anchor_id": "p1-b0"},
            },
        ],
        graph_edges=[],
        version_id="ver_result_seed",
        max_candidates=8,
    )

    assert candidates
    assert candidates[0]["conclusion_node_id"] == "node_result"
    assert "node_method" in candidates[0]["key_support_node_ids"]
    assert "node_dataset" in candidates[0]["key_support_node_ids"]
    assert "node_condition" not in candidates[0]["key_support_node_ids"]


def test_slice7_candidate_builder_prefers_conclusion_over_hypothesis() -> None:
    builder = RouteCandidateBuilder()
    candidates = builder.build_candidates(
        workspace_id="ws_slice7_conclusion_priority",
        graph_nodes=[
            {
                "node_id": "node_hypothesis",
                "workspace_id": "ws_slice7_conclusion_priority",
                "node_type": "assumption",
                "object_ref_type": "assumption",
                "object_ref_id": "asm_1",
                "short_label": "H1 hypothesis",
                "status": "active",
                "short_tags": ["hypothesis"],
            },
            {
                "node_id": "node_conclusion",
                "workspace_id": "ws_slice7_conclusion_priority",
                "node_type": "conclusion",
                "object_ref_type": "conclusion",
                "object_ref_id": "con_1",
                "short_label": "Final conclusion",
                "status": "active",
                "short_tags": ["conclusion"],
            },
            {
                "node_id": "node_evidence",
                "workspace_id": "ws_slice7_conclusion_priority",
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evi_1",
                "short_label": "Observed validation result",
                "status": "active",
                "short_tags": ["result"],
            },
        ],
        graph_edges=[
            {
                "edge_id": "edge_hypothesis_link",
                "workspace_id": "ws_slice7_conclusion_priority",
                "source_node_id": "node_hypothesis",
                "target_node_id": "node_conclusion",
                "edge_type": "supports",
                "object_ref_type": "relation_candidate",
                "object_ref_id": "rel_1",
                "strength": 0.8,
                "status": "active",
            },
            {
                "edge_id": "edge_support",
                "workspace_id": "ws_slice7_conclusion_priority",
                "source_node_id": "node_evidence",
                "target_node_id": "node_conclusion",
                "edge_type": "supports",
                "object_ref_type": "relation_candidate",
                "object_ref_id": "rel_2",
                "strength": 0.8,
                "status": "active",
            }
        ],
        version_id="ver_conclusion_priority",
        max_candidates=8,
    )

    assert candidates[0]["conclusion_node_id"] == "node_conclusion"
    assert "node_evidence" in candidates[0]["key_support_node_ids"]


def test_slice7_candidate_builder_rejects_hypothesis_only_support() -> None:
    builder = RouteCandidateBuilder()
    candidates = builder.build_candidates(
        workspace_id="ws_slice7_hypothesis_only_support",
        graph_nodes=[
            {
                "node_id": "node_hypothesis",
                "workspace_id": "ws_slice7_hypothesis_only_support",
                "node_type": "assumption",
                "object_ref_type": "assumption",
                "object_ref_id": "asm_1",
                "short_label": "H1 hypothesis",
                "status": "active",
                "short_tags": ["hypothesis"],
            },
            {
                "node_id": "node_conclusion",
                "workspace_id": "ws_slice7_hypothesis_only_support",
                "node_type": "conclusion",
                "object_ref_type": "conclusion",
                "object_ref_id": "con_1",
                "short_label": "Final conclusion",
                "status": "active",
                "short_tags": ["conclusion"],
            },
        ],
        graph_edges=[
            {
                "edge_id": "edge_hypothesis_only",
                "workspace_id": "ws_slice7_hypothesis_only_support",
                "source_node_id": "node_hypothesis",
                "target_node_id": "node_conclusion",
                "edge_type": "supports",
                "object_ref_type": "relation_candidate",
                "object_ref_id": "rel_1",
                "strength": 0.8,
                "status": "active",
            }
        ],
        version_id="ver_hypothesis_only_support",
        max_candidates=8,
    )

    assert candidates == []


def test_slice7_candidate_builder_never_uses_gap_as_route_seed_when_claim_exists() -> None:
    builder = RouteCandidateBuilder()
    candidates = builder.build_candidates(
        workspace_id="ws_slice7_gap_gate",
        graph_nodes=[
            {
                "node_id": "node_evidence",
                "workspace_id": "ws_slice7_gap_gate",
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evi_1",
                "short_label": "Measured improvement",
                "status": "active",
            },
            {
                "node_id": "node_conclusion",
                "workspace_id": "ws_slice7_gap_gate",
                "node_type": "conclusion",
                "object_ref_type": "conclusion",
                "object_ref_id": "con_1",
                "short_label": "Main conclusion",
                "status": "active",
            },
            {
                "node_id": "node_gap",
                "workspace_id": "ws_slice7_gap_gate",
                "node_type": "gap",
                "object_ref_type": "gap",
                "object_ref_id": "gap_1",
                "short_label": "Future work",
                "status": "active",
            },
        ],
        graph_edges=[
            {
                "edge_id": "edge_support",
                "workspace_id": "ws_slice7_gap_gate",
                "source_node_id": "node_evidence",
                "target_node_id": "node_conclusion",
                "edge_type": "supports",
                "object_ref_type": "relation_candidate",
                "object_ref_id": "rel_1",
                "strength": 0.8,
                "status": "active",
            },
            {
                "edge_id": "edge_gap",
                "workspace_id": "ws_slice7_gap_gate",
                "source_node_id": "node_conclusion",
                "target_node_id": "node_gap",
                "edge_type": "leaves_gap",
                "object_ref_type": "relation_candidate",
                "object_ref_id": "rel_2",
                "strength": 0.7,
                "status": "active",
            },
        ],
        version_id="ver_gap_gate",
        max_candidates=8,
    )

    assert candidates
    assert all(candidate["conclusion_node_id"] != "node_gap" for candidate in candidates)
    assert candidates[0]["conclusion_node_id"] == "node_conclusion"
    assert "node_gap" in candidates[0]["risk_node_ids"]


def test_slice7_candidate_builder_rejects_unsupported_gap_only_route() -> None:
    builder = RouteCandidateBuilder()
    candidates = builder.build_candidates(
        workspace_id="ws_slice7_gap_only",
        graph_nodes=[
            {
                "node_id": "node_gap",
                "workspace_id": "ws_slice7_gap_only",
                "node_type": "gap",
                "object_ref_type": "gap",
                "object_ref_id": "gap_1",
                "short_label": "Unresolved limitation",
                "status": "active",
            }
        ],
        graph_edges=[],
        version_id="ver_gap_only",
        max_candidates=8,
    )

    assert candidates == []


def test_slice7_candidate_builder_requires_support_for_claim_route() -> None:
    builder = RouteCandidateBuilder()
    candidates = builder.build_candidates(
        workspace_id="ws_slice7_unsupported_claim",
        graph_nodes=[
            {
                "node_id": "node_claim",
                "workspace_id": "ws_slice7_unsupported_claim",
                "node_type": "conclusion",
                "object_ref_type": "conclusion",
                "object_ref_id": "con_1",
                "short_label": "Unsupported conclusion",
                "status": "active",
            }
        ],
        graph_edges=[],
        version_id="ver_unsupported_claim",
        max_candidates=8,
    )

    assert candidates == []


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


def test_slice7_ranker_prefers_claim_centered_routes_over_evidence_centered_routes() -> None:
    ranker = RouteRanker()
    routes = [
        {
            "route_id": "route_evidence",
            "confidence_score": 90.0,
            "support_score": 95.0,
            "risk_score": 5.0,
            "progressability_score": 90.0,
            "relation_tags": ["direct_support", "evidence_centered"],
        },
        {
            "route_id": "route_claim",
            "confidence_score": 70.0,
            "support_score": 70.0,
            "risk_score": 20.0,
            "progressability_score": 70.0,
            "relation_tags": ["direct_support", "claim_centered"],
        },
    ]

    ranked = ranker.rank_routes(routes)

    assert [route["route_id"] for route in ranked] == ["route_claim", "route_evidence"]


def test_slice7_route_generation_marks_route_center_type(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = RouteGenerationService(store)

    claim_tags = service._build_relation_tags(
        candidate={
            "conclusion_node_id": "node_claim",
            "route_node_ids": ["node_claim", "node_support"],
            "key_support_node_ids": ["node_support"],
            "key_assumption_node_ids": [],
            "risk_node_ids": [],
        },
        node_map={
            "node_claim": {"node_id": "node_claim", "node_type": "conclusion"},
            "node_support": {"node_id": "node_support", "node_type": "evidence"},
        },
    )
    evidence_tags = service._build_relation_tags(
        candidate={
            "conclusion_node_id": "node_result",
            "route_node_ids": ["node_result", "node_support"],
            "key_support_node_ids": ["node_support"],
            "key_assumption_node_ids": [],
            "risk_node_ids": [],
        },
        node_map={
            "node_result": {"node_id": "node_result", "node_type": "evidence"},
            "node_support": {"node_id": "node_support", "node_type": "evidence"},
        },
    )

    assert "claim_centered" in claim_tags
    assert "evidence_centered" in evidence_tags


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
    assert "full_description" in prompt
    assert "source_quote" in prompt
    assert "Preserve technical terms" in prompt
    assert "route_edge_ids_json is empty" in prompt
    assert "Do not fabricate" in prompt
    assert "Do not modify any ranking or score" in prompt


def test_slice7_summarizer_context_keeps_full_text_and_source_quote() -> None:
    summarizer = RouteSummarizer()
    structured = summarizer._build_structured_context(
        candidate={
            "conclusion_node_id": "node_result",
            "route_node_ids": ["node_result", "node_method"],
            "key_support_node_ids": ["node_method"],
            "key_assumption_node_ids": [],
            "risk_node_ids": [],
            "next_validation_action": "validate",
            "trace_refs": {"version_id": "ver_1", "route_edge_ids": []},
        },
        node_map={
            "node_result": {
                "node_id": "node_result",
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evi_result",
                "short_label": "Weak parallel scaling tests show AIF...",
                "full_description": "Weak parallel scaling tests show AIFS scales quasi-linearly up to at least 2048 GPUs.",
                "source_ref": {
                    "quote": "Weak parallel scaling tests show AIFS scales quasi-linearly up to at least 2048 GPUs.",
                    "anchor_id": "p6-b0",
                    "source_span": {"page": 6},
                },
                "status": "active",
            },
            "node_method": {
                "node_id": "node_method",
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evi_method",
                "short_label": "AIFS has two sequence parallelism implementations",
                "full_description": "AIFS has two sequence parallelism implementations.",
                "source_ref": {"quote": "two sequence parallelism implementations"},
                "status": "active",
            },
        },
        top_factors=[],
    )

    assert (
        structured["conclusion"]
        == "Weak parallel scaling tests show AIFS scales quasi-linearly up to at least 2048 GPUs."
    )
    assert structured["conclusion_node"]["full_description"] == structured["conclusion"]
    assert structured["conclusion_node"]["source_quote"] == structured["conclusion"]
    assert structured["conclusion_node"]["source_page"] == "6"


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
async def test_slice7_summarizer_replaces_raw_node_ids_in_human_summary(
    monkeypatch,
) -> None:
    summarizer = RouteSummarizer()

    class _FakeGateway:
        async def invoke_json(self, **_: object):
            from research_layer.services.llm_trace import LLMCallResult

            return LLMCallResult(
                provider_backend="unit_test",
                provider_model="unit_model",
                request_id="req_raw_node_id",
                llm_response_id="resp_raw_node_id",
                usage={},
                raw_text="{}",
                parsed_json={
                    "summary": "node_support directly supports node_conclusion.",
                    "key_strengths": [
                        {"text": "node_support is the strongest evidence.", "node_refs": ["node_support"]}
                    ],
                    "key_risks": [
                        {"text": "node_conclusion still needs replication.", "node_refs": ["node_conclusion"]}
                    ],
                    "open_questions": [
                        {"text": "Could node_support generalize?", "node_refs": ["node_support"]}
                    ],
                },
                fallback_used=False,
                degraded=False,
                degraded_reason=None,
            )

    summarizer._gateway = _FakeGateway()  # type: ignore[assignment]

    summary, _ = await summarizer.summarize(
        candidate={
            "conclusion_node_id": "node_conclusion",
            "route_node_ids": ["node_conclusion", "node_support"],
            "key_support_node_ids": ["node_support"],
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
                "short_label": "AIFS produces skilled forecasts",
                "full_description": "AIFS produces skilled forecasts.",
                "status": "active",
            },
            "node_support": {
                "node_id": "node_support",
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evi_2",
                "short_label": "AIFS uses ERA5 training data",
                "full_description": "AIFS uses ERA5 training data.",
                "status": "active",
            },
        },
        top_factors=[],
        request_id="req_raw_node_id",
        allow_fallback=False,
    )

    assert "node_support" not in summary["summary"]
    assert "node_conclusion" not in summary["summary"]
    assert "AIFS uses ERA5 training data" in summary["summary"]
    assert "AIFS produces skilled forecasts" in summary["summary"]
    structured_text = " ".join(
        str(item["text"])
        for field in ("key_strengths", "key_risks", "open_questions")
        for item in summary[field]
    )
    assert "node_support" not in structured_text
    assert "node_conclusion" not in structured_text
    assert "AIFS uses ERA5 training data" in structured_text
    assert "AIFS produces skilled forecasts" in structured_text


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
async def test_slice7_summarizer_rejects_unknown_node_refs(monkeypatch) -> None:
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

    from research_layer.services.llm_gateway import ResearchLLMError

    with pytest.raises(ResearchLLMError) as exc_info:
        await summarizer.summarize(
            candidate=candidate,
            node_map=node_map,
            top_factors=[],
            request_id="req_slice7_unknown_refs",
            allow_fallback=False,
        )

    assert exc_info.value.error_code == "research.llm_invalid_output"
    assert exc_info.value.details["field"] == "key_strengths"
    assert exc_info.value.details["invalid_node_refs"] == ["node_not_in_route"]


@pytest.mark.asyncio
async def test_slice7_summarizer_marks_unknown_node_refs_as_degraded_fallback(
    monkeypatch,
) -> None:
    summarizer = RouteSummarizer()

    class _FakeGateway:
        async def invoke_json(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(
                provider_backend="openai_compatible",
                provider_model="gpt-4.1-mini",
                request_id="req_slice7_unknown_refs_fallback",
                llm_response_id="resp_slice7_unknown_refs_fallback",
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

    summary, trace = await summarizer.summarize(
        candidate={
            "conclusion_node_id": "node_conclusion",
            "route_node_ids": ["node_conclusion", "node_support"],
            "key_support_node_ids": ["node_support"],
            "key_assumption_node_ids": [],
            "risk_node_ids": [],
            "next_validation_action": "validate",
            "trace_refs": {"version_id": "ver_1", "route_edge_ids": []},
        },
        node_map={
            "node_conclusion": {
                "node_id": "node_conclusion",
                "node_type": "conclusion",
                "object_ref_type": "claim",
                "object_ref_id": "claim_1",
                "short_label": "Conclusion claim",
                "status": "active",
            },
            "node_support": {
                "node_id": "node_support",
                "node_type": "evidence",
                "object_ref_type": "evidence",
                "object_ref_id": "evi_1",
                "short_label": "Support evidence",
                "status": "active",
            },
        },
        top_factors=[],
        request_id="req_slice7_unknown_refs_fallback",
        allow_fallback=True,
    )

    assert summary["summary_generation_mode"] == "degraded_fallback"
    assert summary["fallback_used"] is True
    assert summary["degraded"] is True
    assert summary["degraded_reason"] == "research.llm_invalid_output"
    assert trace.fallback_used is True
    assert trace.degraded_reason == "research.llm_invalid_output"


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
