from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from api_specs.dtos.memory import RetrieveMemResponse
from api_specs.memory_models import MemoryType
from api_specs.memory_types import EpisodeMemory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from research_layer.api.controllers import research_graph_controller as graph_module
from research_layer.api.controllers import research_source_controller as source_module
from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.api.controllers.research_graph_controller import ResearchGraphController
from research_layer.api.controllers.research_source_controller import ResearchSourceController
from research_layer.services.evermemos_bridge_service import (
    ResearchMemoryBridge,
    ResearchMemoryRecallService,
)
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


def test_local_source_sync_persists_addressable_memory_link(monkeypatch, tmp_path) -> None:
    store = _store(tmp_path)
    source = store.create_source(
        workspace_id="ws_p2_source_link",
        source_type="paper",
        title="Memory source",
        content="The paper argues that claim ledgers preserve provenance.",
        metadata={},
        import_request_id="req_p2_source_link",
    )
    bridge = ResearchMemoryBridge(store)
    responses = iter([object(), ["log_source"], 1])

    monkeypatch.delenv("RESEARCH_EVERMEMOS_BRIDGE_URL", raising=False)
    monkeypatch.setattr(bridge, "_run_awaitable_blocking", lambda _factory: next(responses))

    link = bridge.sync_source(
        source=source,
        request_id="req_p2_source_link",
        source_hash={"source_id": source["source_id"], "sha256": "hash"},
        artifact_count=1,
    )
    loaded = store.get_source(source_id=str(source["source_id"]))

    assert link["status"] == "written_addressable_ref"
    assert link["memory_id"] == f"local_memory_manager:source:{source['source_id']}"
    assert loaded is not None
    assert loaded["memory_link"]["memory_id"] == link["memory_id"]
    resolved = ResearchRetrievalService(store).resolve_memory_item(
        workspace_id="ws_p2_source_link",
        view_type="evidence",
        result_id=str(link["memory_id"]),
    )
    assert resolved is not None
    assert resolved["supporting_refs"]["source_id"] == source["source_id"]


def test_source_api_response_exposes_memory_link(monkeypatch, tmp_path) -> None:
    store = _store(tmp_path)
    source = store.create_source(
        workspace_id="ws_p2_source_api",
        source_type="paper",
        title="Memory source",
        content="Source content.",
        metadata={},
        import_request_id="req_p2_source_api",
    )
    store.upsert_source_memory_link(
        source_id=str(source["source_id"]),
        workspace_id="ws_p2_source_api",
        memory_id=f"local_memory_manager:source:{source['source_id']}",
        sync_mode="local_memory_manager",
        status="written_addressable_ref",
    )
    monkeypatch.setattr(source_module, "STORE", store)
    app = FastAPI()
    ResearchSourceController().register_to_app(app)
    client = TestClient(app)

    response = client.get(f"/api/v1/research/sources/{source['source_id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["memory_link"]["memory_id"] == (
        f"local_memory_manager:source:{source['source_id']}"
    )


def test_recall_queries_claim_and_source_groups(monkeypatch, tmp_path) -> None:
    store = _store(tmp_path)
    recall_service = ResearchMemoryRecallService(store)
    request_groups: list[str] = []

    class _FakeMemoryManager:
        async def retrieve_mem(self, request):  # type: ignore[no-untyped-def]
            group_id = str(request.group_id or "")
            request_groups.append(group_id)
            if (
                group_id != "research_sources::ws_p2_source_recall"
                or request.memory_types[0] != MemoryType.EPISODIC_MEMORY
            ):
                return RetrieveMemResponse()
            return RetrieveMemResponse(
                memories=[
                    {
                        group_id: [
                            EpisodeMemory(
                                memory_type=MemoryType.EPISODIC_MEMORY,
                                user_id="research_layer_source_bridge",
                                timestamp=datetime.now(timezone.utc),
                                ori_event_id_list=["source::src_p2_recall"],
                                group_id=group_id,
                                id="mem_source_01",
                                summary="Source summary",
                                episode="Source-level memory from EverMemOS.",
                            )
                        ]
                    }
                ],
                scores=[{group_id: [0.83]}],
                importance_scores=[0.0],
                original_data=[],
                total_count=1,
                has_more=False,
            )

    monkeypatch.setattr(recall_service, "_get_memory_manager", lambda: _FakeMemoryManager())

    response = recall_service.recall(
        workspace_id="ws_p2_source_recall",
        query_text="source level memory",
        requested_method="hybrid",
        scope_claim_ids=[],
        scope_mode="prefer",
        top_k=5,
        request_id="req_p2_source_recall",
        trace_refs={"context_type": "source_import", "source_id": "src_p2_recall"},
    )

    assert response["status"] == "completed"
    assert response["items"][0]["memory_id"] == "mem_source_01"
    assert response["items"][0]["linked_source_refs"] == [{"source_id": "src_p2_recall"}]
    assert response["trace_refs"]["group_ids"] == [
        "research_claims::ws_p2_source_recall",
        "research_sources::ws_p2_source_recall",
    ]
    assert "research_claims::ws_p2_source_recall" in request_groups
    assert "research_sources::ws_p2_source_recall" in request_groups


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
    synced: list[dict[str, object]] = []

    def _fake_sync_claim(self, *, claim, request_id, context=None):  # type: ignore[no-untyped-def]
        synced.append(
            {
                "request_id": request_id,
                "claim_id": claim["claim_id"],
                "context": context or {},
            }
        )
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
                    "short_tags": ["memory", "graph"],
                    "visibility": "private",
                    "source_refs": [{"source_id": claim["source_id"], "page": 1}],
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
                    "short_tags": ["updated", "memory"],
                    "visibility": "package_public",
                    "source_refs": [{"source_id": claim["source_id"], "page": 2}],
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

    assert [item["request_id"] for item in synced] == [
        "req_node_create",
        "req_node_patch",
        "req_edge_create",
        "req_edge_patch",
        "req_node_archive",
        "req_edge_archive",
    ]
    node_patch = synced[1]["context"]
    edge_patch = synced[3]["context"]
    node_archive = synced[4]["context"]
    edge_archive = synced[5]["context"]
    assert node_patch["graph_action"] == "node_update"
    assert node_patch["graph_object"]["short_label"] == "Provenance updated"
    assert node_patch["graph_object"]["short_tags"] == ["updated", "memory"]
    assert node_patch["graph_object"]["visibility"] == "package_public"
    assert node_patch["graph_object"]["source_refs"] == [
        {"source_id": claim["source_id"], "page": 2}
    ]
    assert edge_patch["graph_action"] == "edge_update"
    assert edge_patch["graph_object"]["strength"] == 0.8
    assert node_archive["archive_reason"] == "test archive"
    assert node_archive["graph_object"]["status"] == "archived"
    assert edge_archive["archive_reason"] == "test archive"
    assert edge_archive["graph_object"]["status"] == "archived"
