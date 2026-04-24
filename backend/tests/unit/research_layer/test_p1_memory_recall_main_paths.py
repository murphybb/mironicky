from __future__ import annotations

import asyncio
import json

from starlette.requests import Request

from research_layer.api.controllers import research_graph_controller as graph_controller_module
from research_layer.api.controllers import research_route_controller as route_controller_module
from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.api.controllers.research_graph_controller import ResearchGraphController
from research_layer.api.controllers.research_route_controller import ResearchRouteController
from research_layer.services.candidate_confirmation_service import CandidateConfirmationService
from research_layer.graph.repository import GraphRepository
from research_layer.services.graph_build_service import GraphBuildService
from research_layer.services.retrieval_views_service import ResearchRetrievalService


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "research_p1_main_paths.sqlite3"))


def _request(*, body: dict[str, object] | None = None, request_id: str = "req_p1") -> Request:
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


def _seed_workspace_with_graph(
    *, store: ResearchApiStateStore, workspace_id: str
) -> dict[str, object]:
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title="P1 source",
        content=(
            "Claim: retrieval improves accuracy. "
            "Assumption: embeddings remain stable."
        ),
        metadata={},
        import_request_id="req_p1_seed",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id=workspace_id,
        request_id="req_p1_seed",
    )
    batch = store.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        request_id="req_p1_seed",
    )
    created = store.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id=str(job["job_id"]),
        candidates=[
            {
                "candidate_type": "evidence",
                "semantic_type": "result",
                "text": "Claim: retrieval improves accuracy.",
                "source_span": {"start": 0, "end": 35},
                "quote": "Claim: retrieval improves accuracy.",
                "trace_refs": {
                    "source_artifact_id": "art_src_seed_p1-b0",
                    "source_anchor_id": "p1-b0",
                },
                "extractor_name": "evidence_extractor",
            },
            {
                "candidate_type": "assumption",
                "semantic_type": "hypothesis",
                "text": "Assumption: embeddings remain stable.",
                "source_span": {"start": 36, "end": 74},
                "quote": "Assumption: embeddings remain stable.",
                "trace_refs": {
                    "source_artifact_id": "art_src_seed_p1-b1",
                    "source_anchor_id": "p1-b1",
                },
                "extractor_name": "assumption_extractor",
            },
        ],
    )
    confirmation = CandidateConfirmationService(store)
    first = confirmation.confirm(
        workspace_id=workspace_id,
        candidate_id=str(created[0]["candidate_id"]),
        request_id="req_p1_confirm_1",
    )
    second = confirmation.confirm(
        workspace_id=workspace_id,
        candidate_id=str(created[1]["candidate_id"]),
        request_id="req_p1_confirm_2",
    )
    GraphBuildService(GraphRepository(store)).build_workspace_graph(
        workspace_id=workspace_id,
        request_id="req_p1_build",
    )
    nodes = [
        node for node in store.list_graph_nodes(workspace_id) if node["status"] == "active"
    ]
    edges = [
        edge for edge in store.list_graph_edges(workspace_id) if edge["status"] == "active"
    ]
    route = store.create_route(
        workspace_id=workspace_id,
        title="Route title",
        summary="Route summary for recall.",
        status="candidate",
        support_score=0.8,
        risk_score=0.2,
        progressability_score=0.7,
        conclusion="Route conclusion",
        key_supports=["Claim: retrieval improves accuracy."],
        assumptions=["Assumption: embeddings remain stable."],
        risks=[],
        next_validation_action="validate embeddings",
        conclusion_node_id=str(first["graph_node_id"]),
        route_node_ids=[str(node["node_id"]) for node in nodes],
        route_edge_ids=[str(edge["edge_id"]) for edge in edges],
        key_support_node_ids=[str(first["graph_node_id"])],
        key_assumption_node_ids=[str(second["graph_node_id"])],
        risk_node_ids=[],
        version_id="ver_p1_route",
    )
    return {
        "source": source,
        "nodes": nodes,
        "edges": edges,
        "route": route,
    }


def _memory_recall_payload(status: str = "completed") -> dict[str, object]:
    return {
        "status": status,
        "requested_method": "logical",
        "applied_method": "hybrid",
        "reason": "logical_not_supported_by_evermemos" if status == "completed" else "explicit_status",
        "query_text": "Route summary for recall.",
        "total": 1 if status == "completed" else 0,
        "items": (
            [
                {
                    "memory_type": "episodic_memory",
                    "memory_id": "mem_01",
                    "score": 0.91,
                    "title": "Memory title",
                    "snippet": "Memory snippet",
                    "timestamp": "2026-04-24T01:23:00+00:00",
                    "linked_claim_refs": [{"claim_id": "claim_any"}],
                    "trace_refs": {"group_id": "research_claims::ws_p1"},
                }
            ]
            if status == "completed"
            else []
        ),
        "trace_refs": {
            "workspace_id": "ws_p1",
            "group_id": "research_claims::ws_p1",
            "claim_ids": [],
            "context_type": "main_path",
            "context_ref": {},
            "memory_types": ["episodic_memory", "event_log", "foresight"],
            "per_type_count": {},
        },
    }


def test_retrieval_main_path_attaches_memory_recall(monkeypatch, tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_p1_retrieval"
    _seed_workspace_with_graph(store=store, workspace_id=workspace_id)
    service = ResearchRetrievalService(store)
    captured: dict[str, object] = {}

    def _fake_recall(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        payload = _memory_recall_payload()
        payload["trace_refs"]["claim_ids"] = list(kwargs.get("scope_claim_ids", []))
        payload["trace_refs"]["context_ref"] = dict(kwargs.get("trace_refs", {}))
        return payload

    monkeypatch.setattr(service._memory_recall_service, "recall", _fake_recall)

    response = service.retrieve(
        workspace_id=workspace_id,
        view_type="evidence",
        query="retrieval accuracy",
        retrieve_method="logical",
        top_k=5,
        metadata_filters={},
        request_id="req_p1_retrieval",
    )

    assert response["memory_recall"]["status"] == "completed"
    assert captured["requested_method"] == "logical"
    assert captured["trace_refs"]["view_type"] == "evidence"
    assert captured["scope_claim_ids"]


def test_graph_main_paths_expose_memory_recall(monkeypatch, tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_p1_graph"
    seeded = _seed_workspace_with_graph(store=store, workspace_id=workspace_id)
    monkeypatch.setattr(graph_controller_module, "STORE", store)
    controller = ResearchGraphController()

    full_graph = asyncio.run(
        controller.get_graph(workspace_id=workspace_id, request=_request(request_id="req_p1_graph_get"))
    )
    assert full_graph.memory_recall is not None
    assert full_graph.memory_recall.status == "skipped"
    assert full_graph.memory_recall.reason == "graph_recall_requires_center_node; logical_not_supported_by_evermemos"

    captured: dict[str, object] = {}

    def _fake_recall(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        payload = _memory_recall_payload()
        payload["trace_refs"]["claim_ids"] = list(kwargs.get("scope_claim_ids", []))
        return payload

    monkeypatch.setattr(controller._memory_recall_service, "recall", _fake_recall)
    center_node_id = str(seeded["nodes"][0]["node_id"])
    local_graph = asyncio.run(
        controller.query_graph(
            workspace_id=workspace_id,
            request=_request(
                body={"center_node_id": center_node_id, "max_hops": 1},
                request_id="req_p1_graph_query",
            ),
        )
    )

    assert local_graph.memory_recall is not None
    assert local_graph.memory_recall.status == "completed"
    assert captured["requested_method"] == "logical"
    assert captured["scope_mode"] == "require"
    assert captured["scope_claim_ids"]
    assert captured["request_id"] == "req_p1_graph_query"


def test_graph_query_does_not_recall_for_cross_workspace_center_node(
    monkeypatch, tmp_path
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_p1_graph_a"
    other_workspace_id = "ws_p1_graph_b"
    _seed_workspace_with_graph(store=store, workspace_id=workspace_id)
    other = _seed_workspace_with_graph(store=store, workspace_id=other_workspace_id)
    monkeypatch.setattr(graph_controller_module, "STORE", store)
    controller = ResearchGraphController()
    recall_called = False

    def _fake_recall(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal recall_called
        recall_called = True
        return _memory_recall_payload()

    monkeypatch.setattr(controller._memory_recall_service, "recall", _fake_recall)
    center_node_id = str(other["nodes"][0]["node_id"])
    local_graph = asyncio.run(
        controller.query_graph(
            workspace_id=workspace_id,
            request=_request(
                body={"center_node_id": center_node_id, "max_hops": 1},
                request_id="req_p1_graph_cross_workspace",
            ),
        )
    )

    assert local_graph.nodes == []
    assert local_graph.edges == []
    assert local_graph.memory_recall is not None
    assert local_graph.memory_recall.status == "failed"
    assert (
        local_graph.memory_recall.reason
        == "graph_center_node_not_visible_in_workspace; logical_not_supported_by_evermemos"
    )
    assert recall_called is False


def test_route_main_paths_expose_memory_recall(monkeypatch, tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_p1_route"
    seeded = _seed_workspace_with_graph(store=store, workspace_id=workspace_id)
    monkeypatch.setattr(route_controller_module, "STORE", store)
    controller = ResearchRouteController()
    captured_calls: list[dict[str, object]] = []

    def _fake_recall(**kwargs):  # type: ignore[no-untyped-def]
        captured_calls.append(dict(kwargs))
        payload = _memory_recall_payload()
        payload["trace_refs"]["claim_ids"] = list(kwargs.get("scope_claim_ids", []))
        return payload

    monkeypatch.setattr(controller._memory_recall_service, "recall", _fake_recall)
    route_id = str(seeded["route"]["route_id"])

    route_detail = asyncio.run(
        controller.get_route(
            route_id=route_id,
            request=_request(request_id="req_p1_route_detail"),
            workspace_id=workspace_id,
        )
    )
    route_preview = asyncio.run(
        controller.preview_route(
            route_id=route_id,
            request=_request(request_id="req_p1_route_preview"),
            workspace_id=workspace_id,
        )
    )

    assert route_detail.memory_recall is not None
    assert route_detail.memory_recall.status == "completed"
    assert route_preview.memory_recall is not None
    assert route_preview.memory_recall.status == "completed"
    assert len(captured_calls) == 2
    assert all(call["requested_method"] == "logical" for call in captured_calls)
    assert all(call["scope_mode"] == "require" for call in captured_calls)
    assert all(call["scope_claim_ids"] for call in captured_calls)
    assert {call["request_id"] for call in captured_calls} == {
        "req_p1_route_detail",
        "req_p1_route_preview",
    }
