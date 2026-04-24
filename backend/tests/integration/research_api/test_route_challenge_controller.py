from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers.research_route_controller import (
    ResearchRouteController,
)
from research_layer.services.evermemos_bridge_service import EverMemOSRecallService


def _build_test_client() -> TestClient:
    STORE.reset_all()
    app = FastAPI()
    ResearchRouteController().register_to_app(app)
    return TestClient(app)


def _fake_recall(self, **kwargs: object) -> dict[str, object]:
    return {
        "status": "completed",
        "requested_method": kwargs["requested_method"],
        "applied_method": "hybrid",
        "reason": "logical_not_supported_by_evermemos",
        "query_text": kwargs["query_text"],
        "total": 0,
        "items": [],
        "trace_refs": {"scope_claim_ids": kwargs.get("scope_claim_ids", [])},
    }


def _seed_route_with_claim_conflict(workspace_id: str) -> dict[str, object]:
    source = STORE.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="Route challenge source",
        content="Claim: retrieval grounding improves route quality.",
        metadata={},
        import_request_id="req_route_challenge_seed",
    )
    route_claim = STORE.create_claim(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        candidate_id="cand_route_claim",
        claim_type="evidence",
        semantic_type="result",
        text="Claim: retrieval grounding improves route quality.",
        normalized_text="claim: retrieval grounding improves route quality.",
        quote="Claim: retrieval grounding improves route quality.",
        source_span={"start": 0, "end": 49},
        trace_refs={"seed": "route_claim"},
        status="confirmed",
    )
    other_claim = STORE.create_claim(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        candidate_id="cand_other_claim",
        claim_type="evidence",
        semantic_type="result",
        text="Claim: retrieval grounding does not improve route quality.",
        normalized_text="claim: retrieval grounding does not improve route quality.",
        quote="Claim: retrieval grounding does not improve route quality.",
        source_span={"start": 0, "end": 58},
        trace_refs={"seed": "other_claim"},
        status="confirmed",
    )
    node = STORE.create_graph_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="claim",
        object_ref_id=str(route_claim["claim_id"]),
        short_label="Route quality claim",
        full_description=str(route_claim["text"]),
        claim_id=str(route_claim["claim_id"]),
        status="active",
    )
    conflict = STORE.create_claim_conflict(
        workspace_id=workspace_id,
        new_claim_id=str(route_claim["claim_id"]),
        existing_claim_id=str(other_claim["claim_id"]),
        conflict_type="possible_contradiction",
        status="needs_review",
        evidence={"detector": "test"},
        source_ref={"new_claim_id": route_claim["claim_id"]},
        created_request_id="req_route_challenge_seed",
    )
    route = STORE.create_route(
        workspace_id=workspace_id,
        title="Route challenge",
        summary="Route summary",
        status="candidate",
        support_score=0.7,
        risk_score=0.2,
        progressability_score=0.8,
        conclusion="Route conclusion",
        key_supports=["support"],
        assumptions=[],
        risks=[],
        next_validation_action="validate route",
        conclusion_node_id=str(node["node_id"]),
        route_node_ids=[str(node["node_id"])],
        key_support_node_ids=[str(node["node_id"])],
        version_id="ver_route_challenge",
    )
    return {"route": route, "claim": route_claim, "conflict": conflict}


def test_list_routes_returns_claim_ids_and_challenge_refs(monkeypatch) -> None:
    client = _build_test_client()
    seeded = _seed_route_with_claim_conflict("ws_route_challenge_list")
    STORE.create_route(
        workspace_id="ws_route_challenge_list",
        title="Route challenge duplicate",
        summary="Second route summary",
        status="candidate",
        support_score=0.6,
        risk_score=0.3,
        progressability_score=0.7,
        conclusion="Second route conclusion",
        key_supports=["support"],
        assumptions=[],
        risks=[],
        next_validation_action="validate second route",
        conclusion_node_id=str(seeded["route"]["conclusion_node_id"]),
        route_node_ids=list(seeded["route"]["route_node_ids"]),
        key_support_node_ids=list(seeded["route"]["key_support_node_ids"]),
        version_id="ver_route_challenge",
    )
    conflict_list_calls = 0
    original_list_claim_conflicts = STORE.list_claim_conflicts

    def _counting_list_claim_conflicts(**kwargs: object) -> list[dict[str, object]]:
        nonlocal conflict_list_calls
        conflict_list_calls += 1
        return original_list_claim_conflicts(**kwargs)

    monkeypatch.setattr(STORE, "list_claim_conflicts", _counting_list_claim_conflicts)

    response = client.get(
        "/api/v1/research/routes",
        params={"workspace_id": "ws_route_challenge_list"},
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["claim_ids"] == [seeded["claim"]["claim_id"]]
    assert item["challenge_status"] == "needs_review"
    assert item["challenge_refs"]["conflict_ids"] == [
        seeded["conflict"]["conflict_id"]
    ]
    assert conflict_list_calls == 1


def test_get_route_returns_claim_ids_and_challenge_refs(monkeypatch) -> None:
    monkeypatch.setattr(EverMemOSRecallService, "recall", _fake_recall)
    client = _build_test_client()
    seeded = _seed_route_with_claim_conflict("ws_route_challenge_detail")

    response = client.get(
        f"/api/v1/research/routes/{seeded['route']['route_id']}",
        params={"workspace_id": "ws_route_challenge_detail"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["claim_ids"] == [seeded["claim"]["claim_id"]]
    assert payload["challenge_status"] == "needs_review"
    assert payload["challenge_refs"]["conflict_ids"] == [
        seeded["conflict"]["conflict_id"]
    ]
