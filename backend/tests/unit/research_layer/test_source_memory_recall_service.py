from __future__ import annotations

import asyncio

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.source_memory_recall_service import SourceMemoryRecallService


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "source_recall.sqlite3"))


def _seed_source(store: ResearchApiStateStore) -> dict[str, object]:
    return store.create_source(
        workspace_id="ws_source_recall",
        source_type="paper",
        title="new paper",
        content="New claim discusses brand attitude.",
        metadata={},
        import_request_id="req_source_recall",
    )


def test_source_memory_recall_persists_completed_result(monkeypatch, tmp_path) -> None:
    store = _build_store(tmp_path)
    source = _seed_source(store)
    service = SourceMemoryRecallService(store)

    def _fake_recall(**_kwargs):
        return {
            "status": "completed",
            "reason": "logical_not_supported_by_evermemos",
            "requested_method": "logical",
            "applied_method": "hybrid",
            "query_text": "brand attitude claim",
            "total": 1,
            "items": [
                {
                    "memory_type": "episodic_memory",
                    "memory_id": "mem_1",
                    "score": 0.91,
                    "title": "prior claim",
                    "snippet": "Prior claim about brand attitude.",
                    "linked_claim_refs": [{"claim_id": "claim_old"}],
                    "source_ref": {},
                }
            ],
            "trace_refs": {"group_id": "research_claims::ws_source_recall"},
        }

    monkeypatch.setattr(service._memory_recall_service, "recall", _fake_recall)

    result = service.recall_for_source(
        workspace_id="ws_source_recall",
        source_id=str(source["source_id"]),
        query_text="brand attitude claim",
        request_id="req_source_recall",
    )

    assert result["status"] == "completed"
    loaded = store.list_source_memory_recall_results(
        workspace_id="ws_source_recall",
        source_id=str(source["source_id"]),
    )
    assert len(loaded) == 1
    assert loaded[0]["recall_id"] == result["recall_id"]
    assert loaded[0]["total"] == 1
    assert loaded[0]["query_text"] == "brand attitude claim"
    assert loaded[0]["items"][0]["memory_id"] == "mem_1"
    assert loaded[0]["trace_refs"]["group_id"] == "research_claims::ws_source_recall"


def test_source_memory_recall_persists_skipped_result(monkeypatch, tmp_path) -> None:
    store = _build_store(tmp_path)
    source = _seed_source(store)
    service = SourceMemoryRecallService(store)

    monkeypatch.setattr(
        service._memory_recall_service,
        "recall",
        lambda **_kwargs: {
            "status": "skipped",
            "reason": "missing_query_text",
            "requested_method": "logical",
            "applied_method": "hybrid",
            "total": 0,
            "items": [],
            "trace_refs": {"explicit": True},
        },
    )

    result = service.recall_for_source(
        workspace_id="ws_source_recall",
        source_id=str(source["source_id"]),
        query_text="",
        request_id="req_source_recall_skipped",
    )

    assert result["status"] == "skipped"
    loaded = store.get_source_memory_recall_result(str(result["recall_id"]))
    assert loaded is not None
    assert loaded["reason"] == "missing_query_text"
    assert loaded["total"] == 0


def test_source_memory_recall_persists_skipped_result_when_evermemos_unconfigured(
    monkeypatch, tmp_path
) -> None:
    for name in ("MONGODB_HOST", "ES_HOSTS", "MILVUS_HOST"):
        monkeypatch.delenv(name, raising=False)
    store = _build_store(tmp_path)
    source = _seed_source(store)
    service = SourceMemoryRecallService(store)

    result = service.recall_for_source(
        workspace_id="ws_source_recall",
        source_id=str(source["source_id"]),
        query_text="brand attitude claim",
        request_id="req_source_recall_unconfigured",
    )

    assert result["status"] == "skipped"
    assert str(result["reason"]).startswith("evermemos_recall_unconfigured")
    assert result["query_text"] == "brand attitude claim"
    loaded = store.list_source_memory_recall_results(
        workspace_id="ws_source_recall",
        source_id=str(source["source_id"]),
    )
    assert loaded[0]["status"] == "skipped"
    assert str(loaded[0]["reason"]).startswith("evermemos_recall_unconfigured")
    assert loaded[0]["query_text"] == "brand attitude claim"
    reloaded_source = store.get_source(str(source["source_id"]))
    assert reloaded_source is not None
    assert reloaded_source["memory_recall"]["status"] == "skipped"


def test_source_memory_recall_persists_skipped_result_when_evermemos_disabled(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("MONGODB_HOST", "localhost")
    monkeypatch.setenv("ES_HOSTS", "http://localhost:19200")
    monkeypatch.setenv("MILVUS_HOST", "localhost")
    monkeypatch.setenv("RESEARCH_EVERMEMOS_RECALL_DISABLED", "1")
    store = _build_store(tmp_path)
    source = _seed_source(store)
    service = SourceMemoryRecallService(store)

    result = service.recall_for_source(
        workspace_id="ws_source_recall",
        source_id=str(source["source_id"]),
        query_text="brand attitude claim",
        request_id="req_source_recall_disabled",
    )

    assert result["status"] == "skipped"
    assert str(result["reason"]).startswith("evermemos_recall_disabled")
    loaded = store.get_source_memory_recall_result(str(result["recall_id"]))
    assert loaded is not None
    assert loaded["status"] == "skipped"
    assert str(loaded["reason"]).startswith("evermemos_recall_disabled")


def test_source_memory_recall_persists_failed_result_when_recall_raises(tmp_path) -> None:
    store = _build_store(tmp_path)
    source = _seed_source(store)
    service = SourceMemoryRecallService(store)

    def _raise_recall(**_kwargs):
        raise RuntimeError("evermemos unavailable")

    service._memory_recall_service.recall = _raise_recall  # type: ignore[method-assign]

    result = service.recall_for_source(
        workspace_id="ws_source_recall",
        source_id=str(source["source_id"]),
        query_text="brand attitude claim",
        request_id="req_source_recall_failed",
    )

    assert result["status"] == "failed"
    assert result["reason"] == "evermemos unavailable"
    loaded = store.list_source_memory_recall_results(
        workspace_id="ws_source_recall",
        source_id=str(source["source_id"]),
    )
    assert loaded[0]["status"] == "failed"
    assert loaded[0]["request_id"] == "req_source_recall_failed"
    assert loaded[0]["query_text"] == "brand attitude claim"
    assert loaded[0]["error"]["message"] == "evermemos unavailable"
    assert loaded[0]["error"]["type"] == "RuntimeError"
    reloaded_source = store.get_source(str(source["source_id"]))
    assert reloaded_source is not None
    assert (
        reloaded_source["memory_recall"]["error"]["message"]
        == "evermemos unavailable"
    )


def test_source_memory_recall_async_persists_completed_result(monkeypatch, tmp_path) -> None:
    store = _build_store(tmp_path)
    source = _seed_source(store)
    service = SourceMemoryRecallService(store)

    async def _fake_recall_async(**_kwargs):  # type: ignore[no-untyped-def]
        return {
            "status": "completed",
            "reason": "logical_not_supported_by_evermemos",
            "requested_method": "logical",
            "applied_method": "hybrid",
            "query_text": "brand attitude claim",
            "total": 1,
            "items": [{"memory_id": "mem_async_1"}],
            "trace_refs": {"group_id": "research_claims::ws_source_recall"},
        }

    monkeypatch.setattr(service._memory_recall_service, "recall_async", _fake_recall_async)

    result = asyncio.run(
        service.recall_for_source_async(
            workspace_id="ws_source_recall",
            source_id=str(source["source_id"]),
            query_text="brand attitude claim",
            request_id="req_source_recall_async",
        )
    )

    assert result["status"] == "completed"
    loaded = store.get_source_memory_recall_result(str(result["recall_id"]))
    assert loaded is not None
    assert loaded["status"] == "completed"
    assert loaded["items"][0]["memory_id"] == "mem_async_1"


def test_source_memory_recall_async_persists_skipped_result(monkeypatch, tmp_path) -> None:
    store = _build_store(tmp_path)
    source = _seed_source(store)
    service = SourceMemoryRecallService(store)

    async def _fake_recall_async(**_kwargs):  # type: ignore[no-untyped-def]
        return {
            "status": "skipped",
            "reason": "missing_query_text",
            "requested_method": "logical",
            "applied_method": "hybrid",
            "query_text": "",
            "total": 0,
            "items": [],
            "trace_refs": {"explicit": True},
        }

    monkeypatch.setattr(service._memory_recall_service, "recall_async", _fake_recall_async)

    result = asyncio.run(
        service.recall_for_source_async(
            workspace_id="ws_source_recall",
            source_id=str(source["source_id"]),
            query_text="",
            request_id="req_source_recall_async_skipped",
        )
    )

    assert result["status"] == "skipped"
    loaded = store.get_source_memory_recall_result(str(result["recall_id"]))
    assert loaded is not None
    assert loaded["reason"] == "missing_query_text"


def test_source_memory_recall_async_persists_failed_result_when_recall_raises(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    source = _seed_source(store)
    service = SourceMemoryRecallService(store)

    async def _raise_recall_async(**_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("evermemos async unavailable")

    service._memory_recall_service.recall_async = _raise_recall_async  # type: ignore[method-assign]

    result = asyncio.run(
        service.recall_for_source_async(
            workspace_id="ws_source_recall",
            source_id=str(source["source_id"]),
            query_text="brand attitude claim",
            request_id="req_source_recall_async_failed",
        )
    )

    assert result["status"] == "failed"
    loaded = store.get_source_memory_recall_result(str(result["recall_id"]))
    assert loaded is not None
    assert loaded["error"]["message"] == "evermemos async unavailable"
