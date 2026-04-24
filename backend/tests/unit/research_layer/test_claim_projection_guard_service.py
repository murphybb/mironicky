from __future__ import annotations

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.api.schemas.graph import GraphEdgeCreateRequest, GraphNodeCreateRequest
from research_layer.services.claim_projection_guard_service import (
    ClaimProjectionGuardError,
    ClaimProjectionGuardService,
)


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "claim_projection_guard.sqlite3"))


def _seed_claim(store: ResearchApiStateStore, workspace_id: str) -> dict[str, object]:
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="source",
        content="Claim text",
        metadata={},
        import_request_id="req_guard",
    )
    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id="job_guard",
        request_id="req_guard",
    )
    candidates = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id="job_guard",
        candidates=[
            {
                "candidate_type": "claim",
                "text": "Claim text",
                "source_span": {"start": 0, "end": 10},
                "trace_refs": {"source_id": source["source_id"]},
                "extractor_name": "unit",
            }
        ],
    )
    return store.create_claim_from_candidate(
        candidate=candidates[0],
        normalized_text="claim text",
    )


def test_guard_accepts_claim_from_same_workspace(tmp_path) -> None:
    store = _build_store(tmp_path)
    claim = _seed_claim(store, "ws_guard")
    guard = ClaimProjectionGuardService(store)

    result = guard.require_claim(workspace_id="ws_guard", claim_id=str(claim["claim_id"]))

    assert result["claim_id"] == claim["claim_id"]


def test_guard_rejects_missing_claim_id(tmp_path) -> None:
    store = _build_store(tmp_path)
    guard = ClaimProjectionGuardService(store)

    with pytest.raises(ClaimProjectionGuardError) as exc:
        guard.require_claim(workspace_id="ws_guard", claim_id=None)

    assert exc.value.status_code == 400
    assert exc.value.reason == "missing_claim_id"


def test_guard_rejects_cross_workspace_claim(tmp_path) -> None:
    store = _build_store(tmp_path)
    claim = _seed_claim(store, "ws_owner")
    guard = ClaimProjectionGuardService(store)

    with pytest.raises(ClaimProjectionGuardError) as exc:
        guard.require_claim(workspace_id="ws_other", claim_id=str(claim["claim_id"]))

    assert exc.value.reason == "claim_workspace_mismatch"


def test_graph_create_schema_requires_claim_id() -> None:
    assert "claim_id" in GraphNodeCreateRequest.model_json_schema()["required"]
    assert "claim_id" in GraphEdgeCreateRequest.model_json_schema()["required"]
