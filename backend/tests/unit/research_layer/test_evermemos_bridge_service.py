from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from api_specs.dtos.memory import RetrieveMemResponse
from api_specs.memory_models import MemoryType, RetrieveMethod
from api_specs.memory_types import EpisodeMemory
from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.evermemos_bridge_service import (
    ResearchMemoryBridge,
    ResearchMemoryRecallService,
)


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "slice4_bridge.sqlite3"))


def _build_claim() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "claim_id": "claim_bridge_01",
        "workspace_id": "ws_bridge_01",
        "source_id": "src_bridge_01",
        "candidate_id": "cand_bridge_01",
        "claim_type": "evidence",
        "semantic_type": "claim",
        "text": "Claim: local bridge writes to EverMemOS ingress.",
        "normalized_text": "claim: local bridge writes to evermemos ingress.",
        "quote": "local bridge writes to EverMemOS ingress",
        "source_span": {"start": 0, "end": 24},
        "trace_refs": {"source_anchor_id": "p1-b0"},
        "created_at": now,
        "updated_at": now,
    }


def test_bridge_local_write_uses_thread_safe_async_bridge_and_marks_written_unaddressable(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("RESEARCH_EVERMEMOS_BRIDGE_URL", raising=False)

    async def _fake_convert(_message_data):  # type: ignore[no-untyped-def]
        return {"memorize_request": "bridge-local"}

    class _FakeMemoryRequestLogService:
        async def save_request_logs(self, **_kwargs):  # type: ignore[no-untyped-def]
            return ["msg_bridge_local_01"]

    class _FakeMemoryManager:
        async def memorize(self, _memorize_request):  # type: ignore[no-untyped-def]
            return 2

    monkeypatch.setattr(
        "research_layer.services.evermemos_bridge_service.convert_simple_message_to_memorize_request",
        _fake_convert,
    )
    store = _build_store(tmp_path)
    bridge = ResearchMemoryBridge(store)
    monkeypatch.setattr(
        bridge,
        "_get_memory_request_log_service",
        lambda: _FakeMemoryRequestLogService(),
    )
    monkeypatch.setattr(bridge, "_get_memory_manager", lambda: _FakeMemoryManager())

    async def _invoke_from_running_loop() -> dict[str, object]:
        return bridge.sync_claim(claim=_build_claim(), request_id="req_bridge_local_01")

    result = asyncio.run(_invoke_from_running_loop())
    event = store.find_latest_event(
        workspace_id="ws_bridge_01",
        event_name="claim_memory_bridge_completed",
        ref_key="claim_id",
        ref_value="claim_bridge_01",
    )

    assert result["status"] == "written_unaddressable"
    assert result["sync_mode"] == "local_memory_manager"
    assert result["memory_id"] is None
    assert result["reason"] == "addressable_memory_id_unavailable"
    assert event is not None
    assert event["status"] == "written_unaddressable"
    assert event["refs"]["memory_id"] is None
    assert event["refs"]["message_log_ref"] == "message_log:msg_bridge_local_01"


def test_bridge_local_write_failure_records_failed_status(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("RESEARCH_EVERMEMOS_BRIDGE_URL", raising=False)

    async def _fake_convert(_message_data):  # type: ignore[no-untyped-def]
        return {"memorize_request": "bridge-local"}

    class _FailingMemoryRequestLogService:
        async def save_request_logs(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("memory log unavailable")

    monkeypatch.setattr(
        "research_layer.services.evermemos_bridge_service.convert_simple_message_to_memorize_request",
        _fake_convert,
    )
    store = _build_store(tmp_path)
    bridge = ResearchMemoryBridge(store)
    monkeypatch.setattr(
        bridge,
        "_get_memory_request_log_service",
        lambda: _FailingMemoryRequestLogService(),
    )

    result = bridge.sync_claim(claim=_build_claim(), request_id="req_bridge_local_02")

    assert result["status"] == "failed"
    assert result["sync_mode"] == "local_memory_manager"
    assert "memory log unavailable" in str(result["reason"])


def test_bridge_local_write_marks_logged_only_when_memorize_returns_zero(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("RESEARCH_EVERMEMOS_BRIDGE_URL", raising=False)

    async def _fake_convert(_message_data):  # type: ignore[no-untyped-def]
        return {"memorize_request": "bridge-local"}

    class _FakeMemoryRequestLogService:
        async def save_request_logs(self, **_kwargs):  # type: ignore[no-untyped-def]
            return ["msg_bridge_local_02"]

    class _ZeroMemoryManager:
        async def memorize(self, _memorize_request):  # type: ignore[no-untyped-def]
            return 0

    monkeypatch.setattr(
        "research_layer.services.evermemos_bridge_service.convert_simple_message_to_memorize_request",
        _fake_convert,
    )
    store = _build_store(tmp_path)
    bridge = ResearchMemoryBridge(store)
    monkeypatch.setattr(
        bridge,
        "_get_memory_request_log_service",
        lambda: _FakeMemoryRequestLogService(),
    )
    monkeypatch.setattr(bridge, "_get_memory_manager", lambda: _ZeroMemoryManager())

    result = bridge.sync_claim(claim=_build_claim(), request_id="req_bridge_local_03")
    event = store.find_latest_event(
        workspace_id="ws_bridge_01",
        event_name="claim_memory_bridge_completed",
        ref_key="claim_id",
        ref_value="claim_bridge_01",
    )

    assert result["status"] == "logged_only"
    assert result["sync_mode"] == "local_memory_manager"
    assert result["memory_id"] is None
    assert result["reason"] == "memorize_returned_zero"
    assert event is not None
    assert event["status"] == "logged_only"
    assert event["refs"]["memory_id"] is None
    assert event["refs"]["message_log_ref"] == "message_log:msg_bridge_local_02"


def test_recall_maps_logical_to_hybrid_and_links_claim_ids(
    monkeypatch, tmp_path
) -> None:
    store = _build_store(tmp_path)
    recall_service = ResearchMemoryRecallService(store)
    request_log: list[tuple[RetrieveMethod, str, str]] = []

    class _FakeMemoryManager:
        async def retrieve_mem(self, request):  # type: ignore[no-untyped-def]
            request_log.append(
                (
                    request.retrieve_method,
                    request.memory_types[0].value,
                    str(request.group_id or ""),
                )
            )
            if request.memory_types[0] != MemoryType.EPISODIC_MEMORY:
                return RetrieveMemResponse()
            return RetrieveMemResponse(
                memories=[
                    {
                        str(request.group_id): [
                            EpisodeMemory(
                                memory_type=MemoryType.EPISODIC_MEMORY,
                                user_id="research_layer_claim_bridge",
                                timestamp=datetime.now(timezone.utc),
                                ori_event_id_list=["claim::claim_bridge_01"],
                                group_id=str(request.group_id),
                                id="mem_ep_01",
                                summary="Bridge summary",
                                episode="Bridge details from EverMemOS.",
                            )
                        ]
                    }
                ],
                scores=[{str(request.group_id): [0.91]}],
                importance_scores=[0.0],
                original_data=[],
                total_count=1,
                has_more=False,
            )

    monkeypatch.setattr(recall_service, "_get_memory_manager", lambda: _FakeMemoryManager())

    response = recall_service.recall_for_claims(
        workspace_id="ws_bridge_01",
        claim_ids=["claim_bridge_01"],
        query_text="retrieve the bridge claim",
        requested_method="logical",
        top_k=5,
        request_id="req_recall_bridge_01",
        context_type="retrieval_view",
        context_ref={"view_type": "evidence"},
    )

    assert response["status"] == "completed"
    assert response["requested_method"] == "logical"
    assert response["applied_method"] == "hybrid"
    assert response["reason"] == "logical_not_supported_by_evermemos"
    assert response["total"] == 1
    assert response["items"][0]["memory_id"] == "mem_ep_01"
    assert response["items"][0]["linked_claim_refs"] == [{"claim_id": "claim_bridge_01"}]
    assert response["trace_refs"]["claim_ids"] == ["claim_bridge_01"]
    assert response["trace_refs"]["context_ref"]["view_type"] == "evidence"
    assert request_log == [
        (RetrieveMethod.HYBRID, "episodic_memory", "research_claims::ws_bridge_01"),
        (RetrieveMethod.HYBRID, "event_log", "research_claims::ws_bridge_01"),
        (RetrieveMethod.HYBRID, "foresight", "research_claims::ws_bridge_01"),
    ]


def test_recall_skips_when_query_and_claim_scope_are_both_missing(tmp_path) -> None:
    store = _build_store(tmp_path)
    recall_service = ResearchMemoryRecallService(store)

    response = recall_service.recall_for_claims(
        workspace_id="ws_bridge_01",
        claim_ids=[],
        query_text="",
        requested_method="hybrid",
        top_k=5,
        request_id="req_recall_bridge_02",
        context_type="route_detail",
        context_ref={"route_id": "route_01"},
    )

    assert response["status"] == "skipped"
    assert response["reason"] == "missing_query_and_claim_scope"
    assert response["total"] == 0
    assert response["trace_refs"]["context_ref"]["route_id"] == "route_01"
    event = store.find_latest_event(
        workspace_id="ws_bridge_01",
        event_name="evermemos_recall_completed",
        ref_key="reason",
        ref_value="missing_query_and_claim_scope",
    )
    assert event is not None
    assert event["status"] == "skipped"
    assert event["request_id"] == "req_recall_bridge_02"


def test_failed_recall_response_emits_completed_event(tmp_path) -> None:
    store = _build_store(tmp_path)
    recall_service = ResearchMemoryRecallService(store)

    response = recall_service.failed(
        workspace_id="ws_bridge_01",
        requested_method="logical",
        reason="route_missing_claim_scope",
        query_text=None,
        request_id="req_recall_bridge_failed",
        trace_refs={"route_id": "route_failed_01"},
    )

    assert response["status"] == "failed"
    event = store.find_latest_event(
        workspace_id="ws_bridge_01",
        event_name="evermemos_recall_completed",
        ref_key="reason",
        ref_value="route_missing_claim_scope; logical_not_supported_by_evermemos",
    )
    assert event is not None
    assert event["status"] == "failed"
    assert event["request_id"] == "req_recall_bridge_failed"
