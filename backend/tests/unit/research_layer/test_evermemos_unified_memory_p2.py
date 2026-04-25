from __future__ import annotations

import asyncio
import json

from starlette.requests import Request

from research_layer.api.controllers import research_graph_controller as graph_module
from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.api.controllers.research_graph_controller import ResearchGraphController
from research_layer.services.evermemos_bridge_service import ResearchMemoryBridge
from research_layer.services.retrieval_views_service import ResearchRetrievalService
from research_layer.services.source_import_service import SourceImportService


def _store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "unified_memory_p2.sqlite3"))


def _request(
    *, body: dict[str, object] | None = None, request_id: str = "req_p2"
) -> Request:
    raw_body = b""
    if body is not None:
        raw_body = json.dumps(body).encode("utf-8")
    consumed = False

    async def receive() -> dict[str, object]:
        nonlocal consumed
        if consumed:
            return {"type": "http.request", "body": b"", "more_body": False}
        consumed = True
        return {"type": "http.request", "body": raw_body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST" if body is not None else "GET",
            "path": "/",
            "headers": [(b"x-request-id", request_id.encode("utf-8"))],
            "query_string": b"",
            "client": ("test", 1234),
            "server": ("testserver", 80),
            "scheme": "http",
            "http_version": "1.1",
        },
        receive,
    )


def _seed_claim(store: ResearchApiStateStore, workspace_id: str) -> dict[str, object]:
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="P2 source",
        content="Claim: stable provenance makes graph memory reliable.",
        metadata={},
        import_request_id="req_seed",
    )
    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id="job_seed",
        request_id="req_seed",
    )
    candidate = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id="job_seed",
        candidates=[
            {
                "candidate_type": "evidence",
                "text": "Claim: stable provenance makes graph memory reliable.",
                "source_span": {"start": 0, "end": 53},
                "trace_refs": {"source_id": source["source_id"]},
                "extractor_name": "test_p2",
            }
        ],
    )[0]
    return store.create_claim_from_candidate(
        candidate=candidate,
        normalized_text=str(candidate["text"]).lower(),
    )


def test_local_claim_sync_returns_addressable_memory_id(monkeypatch, tmp_path) -> None:
    store = _store(tmp_path)
    claim = _seed_claim(store, "ws_p2_claim")
    bridge = ResearchMemoryBridge(store)
    responses = iter([object(), ["log_1"], 1])

    monkeypatch.delenv("RESEARCH_EVERMEMOS_BRIDGE_URL", raising=False)
    monkeypatch.setattr(
        bridge,
        "_run_awaitable_blocking",
        lambda _factory: next(responses),
    )

    link = bridge.sync_claim(claim=claim, request_id="req_p2_claim")

    assert link["status"] == "written_addressable_ref"
    assert link["sync_mode"] == "local_memory_manager"
    assert link["memory_id"] == f"local_memory_manager:claim:{claim['claim_id']}"
    assert link["reason"] is None


def test_local_claim_memory_id_resolves_through_retrieval_service(
    monkeypatch, tmp_path
) -> None:
    store = _store(tmp_path)
    claim = _seed_claim(store, "ws_p2_resolve")
    memory_id = f"local_memory_manager:claim:{claim['claim_id']}"

    resolved = ResearchRetrievalService(store).resolve_memory_item(
        workspace_id="ws_p2_resolve",
        view_type="evidence",
        result_id=memory_id,
    )

    assert resolved is not None
    assert resolved["result_id"] == memory_id
    assert resolved["supporting_refs"]["claim_id"] == claim["claim_id"]
    assert resolved["source_ref"]["source_id"] == claim["source_id"]


def test_source_import_writes_source_memory_before_recall(monkeypatch, tmp_path) -> None:
    store = _store(tmp_path)
    service = SourceImportService(store)
    calls: list[tuple[str, dict[str, object]]] = []

    def _fake_sync_source(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(("sync", kwargs))
        return {
            "status": "written_addressable_ref",
            "memory_id": f"local_memory_manager:source:{kwargs['source']['source_id']}",
        }

    def _fake_recall(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(("recall", kwargs))
        return {"status": "skipped", "items": [], "total": 0}

    monkeypatch.setattr(service._memory_bridge, "sync_source", _fake_sync_source)
    monkeypatch.setattr(
        service._source_memory_recall_service,
        "recall_for_source",
        _fake_recall,
    )

    source = service.import_source(
        workspace_id="ws_p2_source",
        source_type="paper",
        title="Memory source",
        content="The paper argues that claim ledgers preserve provenance.",
        metadata={},
        request_id="req_p2_source",
    )

    assert [name for name, _ in calls] == ["sync", "recall"]
    assert calls[0][1]["source"]["source_id"] == source["source_id"]
    assert calls[0][1]["source_hash"]["source_id"] == source["source_id"]
    assert calls[0][1]["artifact_count"] >= 1
    assert calls[1][1]["source_id"] == source["source_id"]


def test_source_import_still_emits_source_bridge_events_when_artifact_count_fails(
    monkeypatch, tmp_path
) -> None:
    store = _store(tmp_path)
    service = SourceImportService(store)
    responses = iter([object(), ["log_source"], 1])

    monkeypatch.delenv("RESEARCH_EVERMEMOS_BRIDGE_URL", raising=False)
    monkeypatch.setattr(
        service._source_memory_recall_service,
        "recall_for_source",
        lambda **_kwargs: {"status": "skipped", "items": [], "total": 0},
    )
    monkeypatch.setattr(
        store,
        "list_source_artifacts",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("artifact lookup failed")),
    )
    monkeypatch.setattr(
        service._memory_bridge,
        "_run_awaitable_blocking",
        lambda _factory: next(responses),
    )

    source = service.import_source(
        workspace_id="ws_p2_source_failure",
        source_type="paper",
        title="Memory source",
        content="The paper argues that claim ledgers preserve provenance.",
        metadata={},
        request_id="req_p2_source_failure",
    )

    events = store.list_events(
        workspace_id="ws_p2_source_failure",
        request_id="req_p2_source_failure",
        limit=50,
    )
    assert source["source_id"]
    assert any(event["event_name"] == "source_memory_bridge_started" for event in events)
    assert any(event["event_name"] == "source_memory_bridge_completed" for event in events)


def test_graph_node_create_patch_and_edge_archive_resync_claim_memory(
    monkeypatch, tmp_path
) -> None:
    store = _store(tmp_path)
    workspace_id = "ws_p2_graph"
    claim = _seed_claim(store, workspace_id)
    synced: list[str] = []

    def _fake_sync_claim(self, *, claim, request_id):  # type: ignore[no-untyped-def]
        synced.append(f"{request_id}:{claim['claim_id']}")
        return {"status": "synced", "memory_id": f"mem_{claim['claim_id']}"}

    monkeypatch.setattr(graph_module, "STORE", store)
    monkeypatch.setattr(ResearchMemoryBridge, "sync_claim", _fake_sync_claim)
    controller = ResearchGraphController()

    created = asyncio.run(
        controller.create_graph_node(
            _request(
                body={
                    "workspace_id": workspace_id,
                    "node_type": "evidence",
                    "object_ref_type": "claim",
                    "object_ref_id": str(claim["claim_id"]),
                    "short_label": "Provenance",
                    "full_description": "Stable provenance makes memory reliable.",
                    "claim_id": str(claim["claim_id"]),
                },
                request_id="req_node_create",
            )
        )
    )
    asyncio.run(
        controller.patch_graph_node(
            created.node_id,
            _request(
                body={
                    "workspace_id": workspace_id,
                    "short_label": "Provenance updated",
                },
                request_id="req_node_patch",
            ),
        )
    )
    target = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="conclusion",
        object_ref_type="claim",
        object_ref_id=str(claim["claim_id"]),
        short_label="Target",
        full_description="Target node",
        claim_id=str(claim["claim_id"]),
    )
    edge = store.create_graph_edge(
        workspace_id=workspace_id,
        source_node_id=created.node_id,
        target_node_id=str(target["node_id"]),
        edge_type="supports",
        object_ref_type="claim",
        object_ref_id=str(claim["claim_id"]),
        strength=0.7,
        claim_id=str(claim["claim_id"]),
    )
    asyncio.run(
        controller.create_graph_edge(
            _request(
                body={
                    "workspace_id": workspace_id,
                    "source_node_id": created.node_id,
                    "target_node_id": str(target["node_id"]),
                    "edge_type": "supports",
                    "object_ref_type": "claim",
                    "object_ref_id": str(claim["claim_id"]),
                    "strength": 0.6,
                    "claim_id": str(claim["claim_id"]),
                },
                request_id="req_edge_create",
            )
        )
    )
    asyncio.run(
        controller.patch_graph_edge(
            str(edge["edge_id"]),
            _request(
                body={"workspace_id": workspace_id, "strength": 0.8},
                request_id="req_edge_patch",
            ),
        )
    )
    asyncio.run(
        controller.archive_graph_node(
            created.node_id,
            _request(
                body={"workspace_id": workspace_id, "reason": "test archive"},
                request_id="req_node_archive",
            ),
        )
    )
    asyncio.run(
        controller.archive_graph_edge(
            str(edge["edge_id"]),
            _request(
                body={"workspace_id": workspace_id, "reason": "test archive"},
                request_id="req_edge_archive",
            ),
        )
    )

    assert synced == [
        f"req_node_create:{claim['claim_id']}",
        f"req_node_patch:{claim['claim_id']}",
        f"req_edge_create:{claim['claim_id']}",
        f"req_edge_patch:{claim['claim_id']}",
        f"req_node_archive:{claim['claim_id']}",
        f"req_edge_archive:{claim['claim_id']}",
    ]
