from __future__ import annotations

import sqlite3
import json
import urllib.error

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.candidate_confirmation_service import (
    CandidateConfirmationError,
    CandidateConfirmationService,
)


def _build_store(tmp_path) -> ResearchApiStateStore:
    db_path = tmp_path / "slice4_service.sqlite3"
    return ResearchApiStateStore(db_path=str(db_path))


def _seed_pending_candidate(
    *,
    store: ResearchApiStateStore,
    workspace_id: str,
    source_text: str,
) -> dict[str, object]:
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="slice4 seed",
        content=source_text,
        metadata={},
        import_request_id="req_seed",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id=workspace_id,
        request_id="req_seed",
    )
    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        request_id="req_seed",
    )
    candidates = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        candidates=[
            {
                "candidate_type": "evidence",
                "text": source_text,
                "source_span": {"start": 0, "end": max(1, len(source_text))},
                "quote": source_text,
                "trace_refs": {
                    "source_artifact_id": "art_src_seed_p1-b0",
                    "source_anchor_id": "p1-b0",
                },
                "extractor_name": "evidence_extractor",
            }
        ],
    )
    return candidates[0]


def test_confirm_promotes_pending_candidate_and_persists_traceability(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("RESEARCH_EVERMEMOS_BRIDGE_URL", raising=False)

    async def _fake_convert(_message_data):  # type: ignore[no-untyped-def]
        return {"memorize_request": "local-claim"}

    class _FakeMemoryRequestLogService:
        async def save_request_logs(self, **_kwargs):  # type: ignore[no-untyped-def]
            return ["msg_claim_local_01"]

    class _FakeMemoryManager:
        async def memorize(self, _memorize_request):  # type: ignore[no-untyped-def]
            return 1

    monkeypatch.setattr(
        "research_layer.services.evermemos_bridge_service.convert_simple_message_to_memorize_request",
        _fake_convert,
    )
    monkeypatch.setattr(
        "research_layer.services.evermemos_bridge_service.ResearchMemoryBridge._get_memory_request_log_service",
        lambda self: _FakeMemoryRequestLogService(),
    )
    monkeypatch.setattr(
        "research_layer.services.evermemos_bridge_service.ResearchMemoryBridge._get_memory_manager",
        lambda self: _FakeMemoryManager(),
    )
    store = _build_store(tmp_path)
    service = CandidateConfirmationService(store)
    candidate = _seed_pending_candidate(
        store=store,
        workspace_id="ws_slice4_unit",
        source_text="Claim: retrieval improves accuracy.",
    )

    result = service.confirm(
        workspace_id="ws_slice4_unit",
        candidate_id=str(candidate["candidate_id"]),
        request_id="req_confirm_01",
    )

    assert result["candidate_status"] == "confirmed"
    assert result["claim_id"]
    assert result["claim_memory_sync_status"] == "written_unaddressable"
    assert result["formal_object_type"] == "evidence"
    assert result["formal_object_id"]

    reloaded = store.get_candidate(str(candidate["candidate_id"]))
    claim = store.get_claim_by_candidate_id(
        workspace_id="ws_slice4_unit",
        candidate_id=str(candidate["candidate_id"]),
    )
    assert reloaded is not None
    assert reloaded["status"] == "confirmed"
    assert claim is not None
    assert claim["claim_id"] == result["claim_id"]
    assert claim["status"] == "confirmed"
    assert claim["memory_link"] is not None
    assert claim["memory_link"]["status"] == "written_unaddressable"
    assert claim["memory_link"]["sync_mode"] == "local_memory_manager"
    assert claim["memory_link"]["memory_id"] is None
    assert result["graph_node_id"]
    assert result["graph_version_id"]
    assert isinstance(result["graph_edge_ids"], list)

    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            """
            SELECT candidate_id, source_id, candidate_batch_id, extraction_job_id
            FROM research_evidences
            WHERE evidence_id = ?
            """,
            (result["formal_object_id"],),
        ).fetchone()
        graph_node_row = conn.execute(
            """
            SELECT node_id, object_ref_type, object_ref_id, claim_id, source_ref_json, status, source_refs_json
            FROM graph_nodes
            WHERE node_id = ?
            """,
            (result["graph_node_id"],),
        ).fetchone()
        assert graph_node_row is not None
        assert graph_node_row[1] == result["formal_object_type"]
        assert graph_node_row[2] == result["formal_object_id"]
        assert graph_node_row[3] == result["claim_id"]
        source_ref = json.loads(graph_node_row[4])
        assert source_ref["source_id"] == str(candidate["source_id"])
        assert source_ref["claim_id"] == result["claim_id"]
        assert graph_node_row[5] == "active"
        source_refs = json.loads(graph_node_row[6])
        assert source_refs[0]["quote"] == "Claim: retrieval improves accuracy."
        assert source_refs[0]["artifact_id"] == "art_src_seed_p1-b0"
        assert source_refs[0]["anchor_id"] == "p1-b0"
        assert source_refs[0]["claim_id"] == result["claim_id"]

        version_row = conn.execute(
            """
            SELECT version_id, trigger_type, request_id
            FROM graph_versions
            WHERE version_id = ?
            """,
            (result["graph_version_id"],),
        ).fetchone()
        assert version_row is not None
        assert version_row[1] == "confirm_candidate"
        assert version_row[2] == "req_confirm_01"

        workspace_row = conn.execute(
            """
            SELECT latest_version_id
            FROM graph_workspaces
            WHERE workspace_id = ?
            """,
            ("ws_slice4_unit",),
        ).fetchone()
    assert row is not None
    assert row[0] == str(candidate["candidate_id"])
    assert row[1] == str(candidate["source_id"])
    assert row[2] == str(candidate["candidate_batch_id"])
    assert row[3] == str(candidate["extraction_job_id"])
    assert workspace_row is not None
    assert workspace_row[0] == result["graph_version_id"]
    event = store.find_latest_event(
        workspace_id="ws_slice4_unit",
        event_name="claim_memory_bridge_completed",
        ref_key="claim_id",
        ref_value=result["claim_id"],
    )
    assert event is not None
    assert event["refs"]["message_log_ref"] == "message_log:msg_claim_local_01"


def test_confirm_bridge_failure_records_failed_status_without_blocking(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("RESEARCH_EVERMEMOS_BRIDGE_URL", "https://bridge.example/sync")
    monkeypatch.setattr(
        "research_layer.services.evermemos_bridge_service.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            urllib.error.URLError("bridge offline")
        ),
    )
    store = _build_store(tmp_path)
    service = CandidateConfirmationService(store)
    candidate = _seed_pending_candidate(
        store=store,
        workspace_id="ws_slice4_bridge_fail",
        source_text="Claim: bridge failures stay non-blocking.",
    )

    result = service.confirm(
        workspace_id="ws_slice4_bridge_fail",
        candidate_id=str(candidate["candidate_id"]),
        request_id="req_bridge_fail_01",
    )

    claim = store.get_claim_by_candidate_id(
        workspace_id="ws_slice4_bridge_fail",
        candidate_id=str(candidate["candidate_id"]),
    )
    event = store.find_latest_event(
        workspace_id="ws_slice4_bridge_fail",
        event_name="claim_memory_bridge_completed",
        ref_key="claim_id",
        ref_value=result["claim_id"],
    )

    assert result["candidate_status"] == "confirmed"
    assert result["claim_memory_sync_status"] == "failed"
    assert claim is not None
    assert claim["memory_link"] is not None
    assert claim["memory_link"]["status"] == "failed"
    assert "transport_error" in str(claim["memory_link"]["reason"])
    assert event is not None
    assert event["status"] == "failed"


def test_repeat_confirm_returns_invalid_state_error(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = CandidateConfirmationService(store)
    candidate = _seed_pending_candidate(
        store=store,
        workspace_id="ws_slice4_repeat",
        source_text="Claim: cache hit ratio matters.",
    )
    candidate_id = str(candidate["candidate_id"])
    service.confirm(
        workspace_id="ws_slice4_repeat",
        candidate_id=candidate_id,
        request_id="req_confirm_first",
    )

    with pytest.raises(CandidateConfirmationError) as exc:
        service.confirm(
            workspace_id="ws_slice4_repeat",
            candidate_id=candidate_id,
            request_id="req_confirm_second",
        )

    assert exc.value.error_code == "research.invalid_state"
    assert exc.value.status_code == 409


def test_confirm_duplicate_text_returns_conflict_signal(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = CandidateConfirmationService(store)

    first = _seed_pending_candidate(
        store=store,
        workspace_id="ws_slice4_conflict",
        source_text="Claim: duplicate evidence text.",
    )
    second = _seed_pending_candidate(
        store=store,
        workspace_id="ws_slice4_conflict",
        source_text="Claim: duplicate evidence text.",
    )

    service.confirm(
        workspace_id="ws_slice4_conflict",
        candidate_id=str(first["candidate_id"]),
        request_id="req_conflict_first",
    )

    with pytest.raises(CandidateConfirmationError) as exc:
        service.confirm(
            workspace_id="ws_slice4_conflict",
            candidate_id=str(second["candidate_id"]),
            request_id="req_conflict_second",
        )

    assert exc.value.error_code == "research.conflict"
    assert exc.value.status_code == 409
    assert exc.value.details["reason"] == "duplicate_confirmed_object"


def test_reject_then_repeat_reject_returns_invalid_state(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = CandidateConfirmationService(store)
    candidate = _seed_pending_candidate(
        store=store,
        workspace_id="ws_slice4_reject",
        source_text="Assumption: model is calibrated.",
    )
    candidate_id = str(candidate["candidate_id"])

    result = service.reject(
        workspace_id="ws_slice4_reject",
        candidate_id=candidate_id,
        reason="not useful",
        request_id="req_reject_first",
    )
    assert result["candidate_status"] == "rejected"

    with pytest.raises(CandidateConfirmationError) as exc:
        service.reject(
            workspace_id="ws_slice4_reject",
            candidate_id=candidate_id,
            reason="repeat reject",
            request_id="req_reject_second",
        )

    assert exc.value.error_code == "research.invalid_state"
    assert exc.value.status_code == 409


def test_confirm_not_found_returns_explicit_not_found(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = CandidateConfirmationService(store)

    with pytest.raises(CandidateConfirmationError) as exc:
        service.confirm(
            workspace_id="ws_slice4_not_found",
            candidate_id="cand_missing",
            request_id="req_confirm_missing",
        )

    assert exc.value.error_code == "research.not_found"
    assert exc.value.status_code == 404


def test_confirm_workspace_mismatch_returns_conflict(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = CandidateConfirmationService(store)
    candidate = _seed_pending_candidate(
        store=store,
        workspace_id="ws_slice4_owner",
        source_text="Claim: workspace ownership must be strict.",
    )

    with pytest.raises(CandidateConfirmationError) as exc:
        service.confirm(
            workspace_id="ws_slice4_other",
            candidate_id=str(candidate["candidate_id"]),
            request_id="req_confirm_wrong_ws",
        )

    assert exc.value.error_code == "research.conflict"
    assert exc.value.status_code == 409


def test_candidate_store_persists_prompt_b_anchor_metadata(tmp_path) -> None:
    store = _build_store(tmp_path)
    source = store.create_source(
        workspace_id="ws_slice4_prompt_b_meta",
        source_type="paper",
        title="prompt b seed",
        content="Claim sentence.",
        metadata={},
        import_request_id="req_prompt_b_meta",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id="ws_slice4_prompt_b_meta",
        request_id="req_prompt_b_meta",
    )
    batch = store.create_candidate_batch(
        workspace_id="ws_slice4_prompt_b_meta",
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        request_id="req_prompt_b_meta",
    )

    created = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id="ws_slice4_prompt_b_meta",
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        candidates=[
            {
                "candidate_type": "conclusion",
                "semantic_type": "claim",
                "text": "The paper concludes retrieval improves accuracy.",
                "source_span": {"page": 1, "block_id": "p1-b0", "paragraph_id": "p1-b0-par0"},
                "quote": "retrieval improves accuracy",
                "trace_refs": {"argument_unit_id": "u1", "block_id": "p1-b0"},
                "extractor_name": "argument_unit_extractor",
            }
        ],
    )

    assert created[0]["candidate_type"] == "conclusion"
    assert created[0]["semantic_type"] == "claim"
    assert created[0]["quote"] == "retrieval improves accuracy"
    assert created[0]["trace_refs"]["argument_unit_id"] == "u1"


def test_confirm_materializes_only_resolved_relation_candidates(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = CandidateConfirmationService(store)
    workspace_id = "ws_slice4_resolved_relations"
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="relation seed",
        content="Evidence supports conclusion. Open question is unresolved.",
        metadata={},
        import_request_id="req_relation_seed",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id=workspace_id,
        request_id="req_relation_seed",
    )
    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        request_id="req_relation_seed",
    )
    candidates = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        candidates=[
            {
                "candidate_type": "evidence",
                "semantic_type": "evidence",
                "text": "Evidence sentence.",
                "source_span": {"page": 1, "block_id": "p1-b0"},
                "quote": "Evidence sentence.",
                "trace_refs": {"argument_unit_id": "u_evidence"},
                "extractor_name": "argument_unit_extractor",
            },
            {
                "candidate_type": "conclusion",
                "semantic_type": "claim",
                "text": "Conclusion sentence.",
                "source_span": {"page": 1, "block_id": "p1-b1"},
                "quote": "Conclusion sentence.",
                "trace_refs": {"argument_unit_id": "u_claim"},
                "extractor_name": "argument_unit_extractor",
            },
        ],
    )
    evidence_candidate_id = str(candidates[0]["candidate_id"])
    conclusion_candidate_id = str(candidates[1]["candidate_id"])
    store.add_relation_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        relations=[
            {
                "source_candidate_id": evidence_candidate_id,
                "target_candidate_id": conclusion_candidate_id,
                "semantic_relation_type": "supports",
                "relation_type": "supports",
                "relation_status": "resolved",
                "quote": "Evidence supports conclusion.",
                "trace_refs": {"block_id": "p1-b0"},
            },
            {
                "source_candidate_id": conclusion_candidate_id,
                "target_candidate_id": evidence_candidate_id,
                "semantic_relation_type": "unknown",
                "relation_type": "conflicts",
                "relation_status": "unresolved",
                "quote": "Open question is unresolved.",
                "trace_refs": {"block_id": "p1-b2"},
            },
        ],
    )

    first = service.confirm(
        workspace_id=workspace_id,
        candidate_id=evidence_candidate_id,
        request_id="req_confirm_evidence",
    )
    second = service.confirm(
        workspace_id=workspace_id,
        candidate_id=conclusion_candidate_id,
        request_id="req_confirm_conclusion",
    )

    edges = store.list_graph_edges(workspace_id)
    active_edges = [edge for edge in edges if edge["status"] == "active"]
    assert first["graph_edge_ids"] == []
    assert len(second["graph_edge_ids"]) == 1
    assert len(active_edges) == 1
    assert active_edges[0]["edge_type"] == "supports"
    assert active_edges[0]["object_ref_type"] == "relation_candidate"


def test_confirm_graph_version_persistence_failure_is_explicit(tmp_path, monkeypatch) -> None:
    store = _build_store(tmp_path)
    service = CandidateConfirmationService(store)
    candidate = _seed_pending_candidate(
        store=store,
        workspace_id="ws_slice4_persist_failure",
        source_text="Claim: persistence failure must be explicit.",
    )

    def _raise(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced version persistence failure")

    monkeypatch.setattr(store, "create_graph_version", _raise)

    with pytest.raises(CandidateConfirmationError) as exc:
        service.confirm(
            workspace_id="ws_slice4_persist_failure",
            candidate_id=str(candidate["candidate_id"]),
            request_id="req_confirm_persist_failure",
        )

    assert exc.value.error_code == "research.version_diff_unavailable"
    assert exc.value.status_code == 409
    reloaded = store.get_candidate(str(candidate["candidate_id"]))
    assert reloaded is not None
    assert reloaded["status"] == "pending"

    with sqlite3.connect(store.db_path) as conn:
        confirmed_count = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM research_evidences WHERE candidate_id = ?)
              + (SELECT COUNT(*) FROM research_assumptions WHERE candidate_id = ?)
              + (SELECT COUNT(*) FROM research_conflicts WHERE candidate_id = ?)
              + (SELECT COUNT(*) FROM research_failures WHERE candidate_id = ?)
              + (SELECT COUNT(*) FROM research_validations WHERE candidate_id = ?)
            """,
            (
                str(candidate["candidate_id"]),
                str(candidate["candidate_id"]),
                str(candidate["candidate_id"]),
                str(candidate["candidate_id"]),
                str(candidate["candidate_id"]),
            ),
        ).fetchone()[0]
        graph_node_count = conn.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE workspace_id = ?",
            ("ws_slice4_persist_failure",),
        ).fetchone()[0]
        graph_edge_count = conn.execute(
            "SELECT COUNT(*) FROM graph_edges WHERE workspace_id = ?",
            ("ws_slice4_persist_failure",),
        ).fetchone()[0]
        version_count = conn.execute(
            "SELECT COUNT(*) FROM graph_versions WHERE workspace_id = ?",
            ("ws_slice4_persist_failure",),
        ).fetchone()[0]
        workspace_count = conn.execute(
            "SELECT COUNT(*) FROM graph_workspaces WHERE workspace_id = ?",
            ("ws_slice4_persist_failure",),
        ).fetchone()[0]
        success_event_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM research_events
            WHERE request_id = 'req_confirm_persist_failure'
              AND workspace_id = 'ws_slice4_persist_failure'
              AND event_name IN (
                'candidate_confirmed',
                'graph_materialization_completed',
                'graph_version_created'
              )
            """,
        ).fetchone()[0]
        failed_event_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM research_events
            WHERE request_id = 'req_confirm_persist_failure'
              AND workspace_id = 'ws_slice4_persist_failure'
              AND event_name = 'candidate_confirmation_failed'
            """,
        ).fetchone()[0]

    assert confirmed_count == 0
    assert graph_node_count == 0
    assert graph_edge_count == 0
    assert version_count == 0
    assert workspace_count == 0
    assert success_event_count == 0
    assert failed_event_count == 1
