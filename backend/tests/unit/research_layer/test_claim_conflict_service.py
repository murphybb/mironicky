from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.claim_conflict_service import ClaimConflictService


def _claim(store: ResearchApiStateStore, workspace_id: str, text: str) -> dict[str, object]:
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title=text[:40],
        content=text,
        metadata={},
        import_request_id="req_conflict",
    )
    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id="job_conflict",
        request_id="req_conflict",
    )
    candidate = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id="job_conflict",
        candidates=[
            {
                "candidate_type": "evidence",
                "text": text,
                "source_span": {"start": 0, "end": len(text)},
                "trace_refs": {"source_id": source["source_id"]},
                "extractor_name": "test_conflict",
            }
        ],
    )[0]
    return store.create_claim_from_candidate(
        candidate=candidate,
        normalized_text=text.lower(),
    )


def test_claim_conflict_service_records_direct_contradiction(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "claim_conflicts.sqlite3"))
    old_claim = _claim(store, "ws_conflict", "Brand trust increases purchase intention.")
    new_claim = _claim(
        store,
        "ws_conflict",
        "Brand trust does not increase purchase intention.",
    )
    service = ClaimConflictService(store)

    result = service.detect_for_claim(
        workspace_id="ws_conflict",
        new_claim_id=str(new_claim["claim_id"]),
        candidate_claim_ids=[str(old_claim["claim_id"])],
        request_id="req_conflict",
    )

    assert result["created_count"] == 1
    conflicts = store.list_claim_conflicts(workspace_id="ws_conflict")
    assert conflicts[0]["new_claim_id"] == new_claim["claim_id"]
    assert conflicts[0]["existing_claim_id"] == old_claim["claim_id"]
    assert conflicts[0]["conflict_type"] == "possible_contradiction"
    assert conflicts[0]["status"] == "needs_review"
    assert conflicts[0]["created_request_id"] == "req_conflict"
    assert conflicts[0]["evidence"]["detector"] == "negation_overlap_v1"


def test_claim_conflict_service_skips_cross_workspace_candidates(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "claim_conflicts.sqlite3"))
    old_claim = _claim(store, "ws_other", "Brand trust increases purchase intention.")
    new_claim = _claim(
        store,
        "ws_conflict",
        "Brand trust does not increase purchase intention.",
    )
    service = ClaimConflictService(store)

    result = service.detect_for_claim(
        workspace_id="ws_conflict",
        new_claim_id=str(new_claim["claim_id"]),
        candidate_claim_ids=[str(old_claim["claim_id"])],
        request_id="req_conflict",
    )

    assert result["created_count"] == 0
    assert store.list_claim_conflicts(workspace_id="ws_conflict") == []


def test_claim_conflict_service_detects_antonym_contradiction(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "claim_conflicts.sqlite3"))
    old_claim = _claim(store, "ws_conflict", "Conversion rates increase after launch.")
    new_claim = _claim(store, "ws_conflict", "Conversion rates decrease after launch.")
    service = ClaimConflictService(store)

    result = service.detect_for_claim(
        workspace_id="ws_conflict",
        new_claim_id=str(new_claim["claim_id"]),
        candidate_claim_ids=[str(old_claim["claim_id"])],
        request_id="req_conflict",
    )

    assert result["created_count"] == 1


def test_claim_conflict_service_does_not_treat_not_only_as_negation(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "claim_conflicts.sqlite3"))
    old_claim = _claim(store, "ws_conflict", "The method is effective and scalable.")
    new_claim = _claim(
        store,
        "ws_conflict",
        "The method is not only effective but scalable.",
    )
    service = ClaimConflictService(store)

    result = service.detect_for_claim(
        workspace_id="ws_conflict",
        new_claim_id=str(new_claim["claim_id"]),
        candidate_claim_ids=[str(old_claim["claim_id"])],
        request_id="req_conflict",
    )

    assert result["created_count"] == 0
    assert store.list_claim_conflicts(workspace_id="ws_conflict") == []


def test_claim_conflict_service_ignores_number_stopword_overlap(tmp_path) -> None:
    store = ResearchApiStateStore(db_path=str(tmp_path / "claim_conflicts.sqlite3"))
    old_claim = _claim(store, "ws_conflict", "2024 expenses increased 10 percent.")
    new_claim = _claim(
        store,
        "ws_conflict",
        "2024 revenue did not increase 10 percent.",
    )
    service = ClaimConflictService(store)

    result = service.detect_for_claim(
        workspace_id="ws_conflict",
        new_claim_id=str(new_claim["claim_id"]),
        candidate_claim_ids=[str(old_claim["claim_id"])],
        request_id="req_conflict",
    )

    assert result["created_count"] == 0
    assert store.list_claim_conflicts(workspace_id="ws_conflict") == []
