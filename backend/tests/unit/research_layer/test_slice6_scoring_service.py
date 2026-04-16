from __future__ import annotations

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.candidate_confirmation_service import CandidateConfirmationService
from research_layer.services.graph_build_service import GraphBuildService
from research_layer.services.score_service import ScoreService, ScoreServiceError
from research_layer.graph.repository import GraphRepository
from research_layer.scoring.explainer import select_top_factors


def _build_store(tmp_path) -> ResearchApiStateStore:
    db_path = tmp_path / "slice6_scoring.sqlite3"
    return ResearchApiStateStore(db_path=str(db_path))


def _seed_confirmed_objects(
    *,
    store: ResearchApiStateStore,
    workspace_id: str,
    include_validation: bool,
) -> list[str]:
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="slice6 source",
        content="Claim: retrieval boosts precision. Assumption: embeddings remain stable. Conflict: noise drift. Failure: latency spike. Validation: run ablation.",
        metadata={},
        import_request_id="req_slice6_seed",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id=workspace_id,
        request_id="req_slice6_seed",
    )
    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        request_id="req_slice6_seed",
    )

    seed_candidates = [
        {
            "candidate_type": "evidence",
            "text": "Claim: retrieval boosts precision.",
            "source_span": {"start": 0, "end": 32},
            "extractor_name": "evidence_extractor",
        },
        {
            "candidate_type": "assumption",
            "text": "Assumption: embeddings remain stable.",
            "source_span": {"start": 33, "end": 70},
            "extractor_name": "assumption_extractor",
        },
        {
            "candidate_type": "conflict",
            "text": "Conflict: noise drift.",
            "source_span": {"start": 71, "end": 92},
            "extractor_name": "conflict_extractor",
        },
        {
            "candidate_type": "failure",
            "text": "Failure: latency spike.",
            "source_span": {"start": 93, "end": 116},
            "extractor_name": "failure_extractor",
        },
    ]
    if include_validation:
        seed_candidates.append(
            {
                "candidate_type": "validation",
                "text": "Validation: run ablation.",
                "source_span": {"start": 117, "end": 141},
                "extractor_name": "validation_extractor",
            }
        )

    created = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        candidates=seed_candidates,
    )
    confirmation = CandidateConfirmationService(store)
    confirmed_ids: list[str] = []
    for idx, candidate in enumerate(created):
        confirmed = confirmation.confirm(
            workspace_id=workspace_id,
            candidate_id=str(candidate["candidate_id"]),
            request_id=f"req_slice6_confirm_{idx}",
        )
        confirmed_ids.append(str(confirmed["formal_object_id"]))
    return confirmed_ids


def _build_route_for_scoring(
    *,
    store: ResearchApiStateStore,
    workspace_id: str,
    include_validation: bool,
) -> tuple[str, list[dict[str, object]]]:
    _seed_confirmed_objects(
        store=store,
        workspace_id=workspace_id,
        include_validation=include_validation,
    )
    graph_repo = GraphRepository(store)
    GraphBuildService(graph_repo).build_workspace_graph(
        workspace_id=workspace_id,
        request_id="req_slice6_build",
    )
    route = store.create_route(
        workspace_id=workspace_id,
        title="Slice6 route",
        summary="Route scored by structured heuristics.",
        status="candidate",
        support_score=0.0,
        risk_score=0.0,
        progressability_score=0.0,
        conclusion="Proceed with controlled validation.",
        key_supports=["source-backed claim"],
        assumptions=["embedding stability"],
        risks=["latency spikes"],
        next_validation_action="run ablation and compare retrieval precision",
    )
    nodes = store.list_graph_nodes(workspace_id)
    return str(route["route_id"]), nodes


def test_score_route_returns_three_scores_and_structured_breakdown(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice6_unit"
    route_id, _ = _build_route_for_scoring(
        store=store,
        workspace_id=workspace_id,
        include_validation=True,
    )

    service = ScoreService(store)
    scored = service.score_route(
        workspace_id=workspace_id,
        route_id=route_id,
        request_id="req_slice6_score",
    )

    for score_field in ("support_score", "risk_score", "progressability_score"):
        assert isinstance(scored[score_field], float)
        assert 0.0 <= scored[score_field] <= 100.0
    assert isinstance(scored["confidence_score"], float)
    assert scored["confidence_grade"] in {"low", "medium", "high"}

    assert scored["top_factors"]
    assert len(scored["top_factors"]) == 3
    assert scored["score_breakdown"]["support_score"]["factors"]
    first_factor = scored["score_breakdown"]["support_score"]["factors"][0]
    assert "factor_name" in first_factor
    assert "normalized_value" in first_factor
    assert "weight" in first_factor
    assert "weighted_contribution" in first_factor
    assert "status" in first_factor
    assert "refs" in first_factor
    assert scored["node_score_breakdown"]
    assert "reviewer_note" in scored["top_factors"][0]
    critique = scored["score_breakdown"]["support_score"]["reviewer_critique"]
    assert critique["readiness"] in {"ready", "needs_revision", "blocked"}
    assert isinstance(critique["blocking_issues"], list)
    assert isinstance(critique["warnings"], list)
    assert isinstance(critique["suggestions"], list)
    if critique["warnings"]:
        warning = critique["warnings"][0]
        assert "issue_code" in warning
        assert "severity" in warning
        assert "message" in warning
        assert "refs" in warning


def test_normalized_factor_weighted_contribution_matches_final_score(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice6_formula"
    route_id, _ = _build_route_for_scoring(
        store=store,
        workspace_id=workspace_id,
        include_validation=True,
    )

    service = ScoreService(store)
    scored = service.score_route(
        workspace_id=workspace_id,
        route_id=route_id,
        request_id="req_slice6_formula",
    )

    support_factors = scored["score_breakdown"]["support_score"]["factors"]
    weighted_sum = sum(float(item["weighted_contribution"]) for item in support_factors)
    expected_support = round(min(max(weighted_sum, 0.0), 1.0) * 100, 1)
    assert scored["support_score"] == expected_support
    expected_confidence = round(
        (
            scored["support_score"]
            + (100.0 - scored["risk_score"])
            + scored["progressability_score"]
        )
        / 3.0,
        1,
    )
    assert scored["confidence_score"] == expected_confidence


def test_top_factor_selection_uses_spec_tie_break_order() -> None:
    factors = [
        {
            "factor_name": "expected_signal_strength",
            "score_dimension": "progressability_score",
            "weighted_contribution": 0.2,
            "normalized_value": 1.0,
            "weight": 0.2,
            "status": "computed",
            "reason": "seed",
            "refs": {},
            "metrics": {},
        },
        {
            "factor_name": "failure_pressure",
            "score_dimension": "risk_score",
            "weighted_contribution": 0.2,
            "normalized_value": 0.8,
            "weight": 0.25,
            "status": "computed",
            "reason": "seed",
            "refs": {},
            "metrics": {},
        },
        {
            "factor_name": "confirmed_evidence_coverage",
            "score_dimension": "support_score",
            "weighted_contribution": 0.2,
            "normalized_value": 0.66,
            "weight": 0.3,
            "status": "computed",
            "reason": "seed",
            "refs": {},
            "metrics": {},
        },
    ]

    top = select_top_factors(factors, limit=3)
    assert [item["factor_name"] for item in top] == [
        "confirmed_evidence_coverage",
        "failure_pressure",
        "expected_signal_strength",
    ]


def test_missing_factor_uses_explicit_missing_semantics(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice6_missing"
    route_id, _ = _build_route_for_scoring(
        store=store,
        workspace_id=workspace_id,
        include_validation=False,
    )

    service = ScoreService(store)
    scored = service.score_route(
        workspace_id=workspace_id,
        route_id=route_id,
        request_id="req_slice6_missing",
    )

    factors = scored["score_breakdown"]["support_score"]["factors"]
    validation_factor = next(item for item in factors if item["factor_name"] == "validation_backing")
    assert validation_factor["normalized_value"] == 0.0
    assert validation_factor["status"] == "missing_input"
    critique = scored["score_breakdown"]["support_score"]["reviewer_critique"]
    issue_codes = {
        str(item["issue_code"])
        for item in critique["blocking_issues"] + critique["warnings"]
        if isinstance(item, dict) and "issue_code" in item
    }
    assert "missing_factor:validation_backing" in issue_codes


def test_invalid_workspace_route_or_graph_refs_raise_explicit_errors(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice6_errors"
    route_id, nodes = _build_route_for_scoring(
        store=store,
        workspace_id=workspace_id,
        include_validation=True,
    )

    service = ScoreService(store)
    with pytest.raises(ScoreServiceError) as wrong_workspace:
        service.score_route(
            workspace_id="ws_other",
            route_id=route_id,
            request_id="req_slice6_wrong_workspace",
        )
    assert wrong_workspace.value.error_code == "research.conflict"

    with pytest.raises(ScoreServiceError) as missing_node:
        service.score_route(
            workspace_id=workspace_id,
            route_id=route_id,
            request_id="req_slice6_missing_node",
            focus_node_ids=["node_missing"],
        )
    assert missing_node.value.error_code == "research.invalid_request"

    target_node_id = str(nodes[0]["node_id"])
    first = service.score_route(
        workspace_id=workspace_id,
        route_id=route_id,
        request_id="req_slice6_before_change",
        focus_node_ids=[target_node_id],
    )
    store.update_graph_node(
        node_id=target_node_id,
        short_label=None,
        full_description=None,
        status="failed",
    )
    second = service.score_route(
        workspace_id=workspace_id,
        route_id=route_id,
        request_id="req_slice6_after_change",
        focus_node_ids=[target_node_id],
    )
    assert first["risk_score"] != second["risk_score"]
