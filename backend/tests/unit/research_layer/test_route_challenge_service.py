from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.route_challenge_service import RouteChallengeService


def _store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "route_challenge.sqlite3"))


def _conflict(
    store: ResearchApiStateStore,
    *,
    workspace_id: str = "ws_route_challenge",
    new_claim_id: str = "claim_route",
    existing_claim_id: str = "claim_other",
    status: str,
) -> dict[str, object]:
    return store.create_claim_conflict(
        workspace_id=workspace_id,
        new_claim_id=new_claim_id,
        existing_claim_id=existing_claim_id,
        conflict_type="possible_contradiction",
        status=status,
        evidence={},
        source_ref={},
        created_request_id="req_route_challenge",
    )


def test_route_challenge_service_returns_clean_without_related_active_conflict(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    _conflict(
        store,
        new_claim_id="claim_unrelated",
        existing_claim_id="claim_other",
        status="needs_review",
    )
    service = RouteChallengeService(store)

    result = service.evaluate_route(
        workspace_id="ws_route_challenge",
        route={"claim_ids": ["claim_route"]},
    )

    assert result == {
        "challenge_status": "clean",
        "conflict_count": 0,
        "conflict_ids": [],
    }


def test_route_challenge_service_marks_needs_review_conflict(tmp_path) -> None:
    store = _store(tmp_path)
    conflict = _conflict(store, status="needs_review")
    service = RouteChallengeService(store)

    result = service.evaluate_route(
        workspace_id="ws_route_challenge",
        route={"claim_ids": ["claim_route"]},
    )

    assert result["challenge_status"] == "needs_review"
    assert result["conflict_count"] == 1
    assert result["conflict_ids"] == [conflict["conflict_id"]]


def test_route_challenge_service_marks_accepted_conflict_as_weakened(tmp_path) -> None:
    store = _store(tmp_path)
    conflict = _conflict(store, existing_claim_id="claim_route", status="accepted")
    service = RouteChallengeService(store)

    result = service.evaluate_route(
        workspace_id="ws_route_challenge",
        route={"claim_ids": ["claim_route"]},
    )

    assert result["challenge_status"] == "weakened"
    assert result["conflict_count"] == 1
    assert result["conflict_ids"] == [conflict["conflict_id"]]


def test_route_challenge_service_ignores_rejected_and_resolved_conflicts(tmp_path) -> None:
    store = _store(tmp_path)
    _conflict(store, status="rejected")
    _conflict(store, existing_claim_id="claim_route", status="resolved")
    service = RouteChallengeService(store)

    result = service.evaluate_route(
        workspace_id="ws_route_challenge",
        route={"claim_ids": ["claim_route"]},
    )

    assert result == {
        "challenge_status": "clean",
        "conflict_count": 0,
        "conflict_ids": [],
    }


def test_route_challenge_service_evaluates_prefetched_conflicts(tmp_path) -> None:
    store = _store(tmp_path)
    conflict = _conflict(store, status="needs_review")
    _conflict(store, new_claim_id="claim_unrelated", status="needs_review")
    service = RouteChallengeService(store)

    result = service.evaluate_route_with_conflicts(
        workspace_id="ws_route_challenge",
        route={"claim_ids": ["claim_route"]},
        conflicts=store.list_claim_conflicts(workspace_id="ws_route_challenge"),
    )

    assert result["challenge_status"] == "needs_review"
    assert result["conflict_count"] == 1
    assert result["conflict_ids"] == [conflict["conflict_id"]]


def test_route_challenge_service_evaluates_conflict_index(tmp_path) -> None:
    store = _store(tmp_path)
    conflict = _conflict(store, status="needs_review")
    _conflict(store, new_claim_id="claim_unrelated", status="needs_review")
    _conflict(store, workspace_id="ws_other", status="needs_review")
    service = RouteChallengeService(store)
    conflicts = [
        *store.list_claim_conflicts(workspace_id="ws_route_challenge"),
        *store.list_claim_conflicts(workspace_id="ws_other"),
    ]

    conflict_index = service.build_conflict_index(
        workspace_id="ws_route_challenge",
        conflicts=conflicts,
    )
    result = service.evaluate_route_with_conflict_index(
        route={"claim_ids": ["claim_route"]},
        conflict_index=conflict_index,
    )

    assert result["challenge_status"] == "needs_review"
    assert result["conflict_count"] == 1
    assert result["conflict_ids"] == [conflict["conflict_id"]]
