from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from research_layer.api.controllers import (
    research_graph_controller as graph_controller_module,
)
from research_layer.api.controllers import (
    research_route_controller as route_controller_module,
)
from research_layer.api.controllers._state_store import ResearchApiStateStore


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "slice12_memory_recall.sqlite3"))


def _make_request(
    *,
    method: str,
    headers: dict[str, str] | None = None,
    payload: dict[str, object] | None = None,
) -> Request:
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    consumed = False

    async def receive() -> dict[str, object]:
        nonlocal consumed
        if consumed:
            return {"type": "http.request", "body": b"", "more_body": False}
        consumed = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": method,
        "path": "/",
        "headers": [
            (key.lower().encode("utf-8"), value.encode("utf-8"))
            for key, value in (headers or {}).items()
        ],
    }
    return Request(scope, receive)


def _seed_claim_node(
    store: ResearchApiStateStore,
    *,
    workspace_id: str,
    seed_id: str,
    node_type: str,
    short_label: str,
    claim_text: str,
) -> tuple[dict[str, object], dict[str, object]]:
    source = store.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title=f"source {seed_id}",
        content=claim_text,
        metadata={},
        import_request_id=f"req_source_{seed_id}",
    )
    claim = store.create_claim(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        candidate_id=f"cand_{seed_id}",
        claim_type=node_type,
        semantic_type=node_type,
        text=claim_text,
        normalized_text=claim_text.lower(),
        quote=claim_text,
        source_span={"start": 0, "end": len(claim_text)},
        trace_refs={"seed_id": seed_id},
        status="confirmed",
    )
    node = store.create_graph_node(
        workspace_id=workspace_id,
        node_type=node_type,
        object_ref_type="claim",
        object_ref_id=str(claim["claim_id"]),
        short_label=short_label,
        full_description=claim_text,
        claim_id=str(claim["claim_id"]),
        status="active",
    )
    return claim, node


class _FakeRecallService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def recall(self, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs)
        self.calls.append(("recall", payload))
        requested_method = str(payload["requested_method"])
        applied_method = "hybrid" if requested_method == "logical" else requested_method
        return {
            "status": "completed",
            "requested_method": requested_method,
            "applied_method": applied_method,
            "reason": (
                "logical_not_supported_by_evermemos"
                if requested_method == "logical"
                else None
            ),
            "query_text": str(payload["query_text"]),
            "total": 1,
            "items": [
                {
                    "memory_type": "event_log",
                    "memory_id": "mem_main_path_01",
                    "score": 0.83,
                    "title": "main path recall",
                    "snippet": "main path recall snippet",
                    "timestamp": "2026-04-24T00:00:00Z",
                    "linked_claim_refs": [],
                    "trace_refs": {},
                }
            ],
            "trace_refs": {"scope_claim_ids": payload.get("scope_claim_ids", [])},
        }

    def skipped(self, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs)
        self.calls.append(("skipped", payload))
        requested_method = str(payload["requested_method"])
        applied_method = "hybrid" if requested_method == "logical" else requested_method
        return {
            "status": "skipped",
            "requested_method": requested_method,
            "applied_method": applied_method,
            "reason": str(payload["reason"]),
            "query_text": str(payload.get("query_text") or ""),
            "total": 0,
            "items": [],
            "trace_refs": payload.get("trace_refs", {}),
        }


@pytest.mark.asyncio
async def test_slice12_graph_controller_get_skips_and_query_recalls_center_claim(
    monkeypatch, tmp_path
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice12_graph_recall"
    center_claim, center_node = _seed_claim_node(
        store,
        workspace_id=workspace_id,
        seed_id="graph_center",
        node_type="conclusion",
        short_label="Center claim",
        claim_text="Center claim states the system should prioritize grounded recall.",
    )
    _, support_node = _seed_claim_node(
        store,
        workspace_id=workspace_id,
        seed_id="graph_support",
        node_type="evidence",
        short_label="Support evidence",
        claim_text="Support evidence links the center claim to prior benchmark observations.",
    )
    store.create_graph_edge(
        workspace_id=workspace_id,
        source_node_id=str(support_node["node_id"]),
        target_node_id=str(center_node["node_id"]),
        edge_type="supports",
        object_ref_type="graph_relation",
        object_ref_id="edge_graph_center",
        strength=0.82,
        status="active",
    )

    monkeypatch.setattr(graph_controller_module, "STORE", store)
    controller = graph_controller_module.ResearchGraphController()
    fake_recall = _FakeRecallService()
    controller._memory_recall_service = fake_recall

    get_response = await controller.get_graph(
        workspace_id=workspace_id,
        request=_make_request(method="GET", headers={"x-request-id": "req_graph_get"}),
    )
    query_response = await controller.query_graph(
        workspace_id=workspace_id,
        request=_make_request(
            method="POST",
            headers={
                "x-request-id": "req_graph_query",
                "content-type": "application/json",
            },
            payload={"center_node_id": str(center_node["node_id"]), "max_hops": 1},
        ),
    )

    assert get_response.memory_recall is not None
    assert get_response.memory_recall.status == "skipped"
    assert get_response.memory_recall.reason == "graph_recall_requires_center_node"
    assert query_response.memory_recall is not None
    assert query_response.memory_recall.status == "completed"
    recall_calls = [payload for kind, payload in fake_recall.calls if kind == "recall"]
    assert recall_calls
    assert recall_calls[0]["requested_method"] == "logical"
    assert recall_calls[0]["scope_mode"] == "require"
    assert recall_calls[0]["scope_claim_ids"] == [str(center_claim["claim_id"])]


@pytest.mark.asyncio
async def test_slice12_route_controller_get_and_preview_attach_memory_recall(
    monkeypatch, tmp_path
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice12_route_recall"
    conclusion_claim, conclusion_node = _seed_claim_node(
        store,
        workspace_id=workspace_id,
        seed_id="route_conclusion",
        node_type="conclusion",
        short_label="Route conclusion",
        claim_text="The route conclusion recommends grounding research decisions in traceable recall.",
    )
    support_claim, support_node = _seed_claim_node(
        store,
        workspace_id=workspace_id,
        seed_id="route_support",
        node_type="evidence",
        short_label="Route support",
        claim_text="The support node shows repeated gains from grounding memory recall in claim scope.",
    )
    risk_claim, risk_node = _seed_claim_node(
        store,
        workspace_id=workspace_id,
        seed_id="route_risk",
        node_type="conflict",
        short_label="Route risk",
        claim_text="The risk node warns that silent downgrade can hide unsupported logical retrieval.",
    )
    edge = store.create_graph_edge(
        workspace_id=workspace_id,
        source_node_id=str(support_node["node_id"]),
        target_node_id=str(conclusion_node["node_id"]),
        edge_type="supports",
        object_ref_type="graph_relation",
        object_ref_id="edge_route_support",
        strength=0.77,
        status="active",
    )
    route = store.create_route(
        workspace_id=workspace_id,
        title="Recall-first route",
        summary="Use real EverMemOS recall on route detail surfaces.",
        status="active",
        support_score=0.84,
        risk_score=0.22,
        progressability_score=0.79,
        conclusion="Attach memory recall to route responses.",
        key_supports=["support node"],
        assumptions=["EverMemOS local recall stays available"],
        risks=["unsupported logical recall must stay explicit"],
        next_validation_action="Inspect route detail and preview payloads.",
        conclusion_node_id=str(conclusion_node["node_id"]),
        route_node_ids=[
            str(conclusion_node["node_id"]),
            str(support_node["node_id"]),
            str(risk_node["node_id"]),
        ],
        route_edge_ids=[str(edge["edge_id"])],
        key_support_node_ids=[str(support_node["node_id"])],
        risk_node_ids=[str(risk_node["node_id"])],
    )

    monkeypatch.setattr(route_controller_module, "STORE", store)
    controller = route_controller_module.ResearchRouteController()
    fake_recall = _FakeRecallService()
    controller._memory_recall_service = fake_recall

    route_response = await controller.get_route(
        route_id=str(route["route_id"]),
        request=_make_request(
            method="GET",
            headers={"x-request-id": "req_slice12_route_detail"},
        ),
        workspace_id=workspace_id,
    )
    preview_response = await controller.preview_route(
        route_id=str(route["route_id"]),
        request=_make_request(
            method="GET",
            headers={"x-request-id": "req_slice12_route_preview"},
        ),
        workspace_id=workspace_id,
    )

    assert route_response.memory_recall is not None
    assert route_response.memory_recall.status == "completed"
    assert preview_response.memory_recall is not None
    assert preview_response.memory_recall.status == "completed"
    recall_calls = [payload for kind, payload in fake_recall.calls if kind == "recall"]
    assert len(recall_calls) == 2
    expected_scope = [
        str(conclusion_claim["claim_id"]),
        str(support_claim["claim_id"]),
        str(risk_claim["claim_id"]),
    ]
    for call in recall_calls:
        assert call["requested_method"] == "logical"
        assert call["scope_mode"] == "require"
        assert call["scope_claim_ids"] == expected_scope
