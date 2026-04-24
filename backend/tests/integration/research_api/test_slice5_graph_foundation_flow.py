from __future__ import annotations

import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers.research_failure_controller import (
    ResearchFailureController,
)
from research_layer.api.controllers.research_graph_controller import (
    ResearchGraphController,
)
from research_layer.api.controllers.research_hypothesis_controller import (
    ResearchHypothesisController,
)
from research_layer.api.controllers.research_job_controller import ResearchJobController
from research_layer.api.controllers.research_package_controller import (
    ResearchPackageController,
)
from research_layer.api.controllers.research_route_controller import (
    ResearchRouteController,
)
from research_layer.api.controllers.research_source_controller import (
    ResearchSourceController,
)
from research_layer.testing.job_helpers import wait_for_job_terminal


def _build_test_client() -> TestClient:
    STORE.reset_all()
    app = FastAPI()
    controllers = [
        ResearchSourceController(),
        ResearchRouteController(),
        ResearchGraphController(),
        ResearchFailureController(),
        ResearchHypothesisController(),
        ResearchPackageController(),
        ResearchJobController(),
    ]
    for controller in controllers:
        controller.register_to_app(app)
    return TestClient(app)


def _import_extract_confirm(
    client: TestClient, *, workspace_id: str, content: str
) -> list[str]:
    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": workspace_id,
            "source_type": "paper",
            "title": "slice5 foundation",
            "content": content,
        },
    )
    assert imported.status_code == 200
    source_id = imported.json()["source_id"]
    extracted = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": workspace_id, "async_mode": True},
        headers={
            "x-research-llm-failure-mode": "timeout",
            "x-research-llm-allow-fallback": "true",
        },
    )
    assert extracted.status_code == 202
    extract_job = wait_for_job_terminal(
        client, job_id=str(extracted.json()["job_id"])
    )
    assert extract_job["status"] == "succeeded"
    listed = client.get(
        "/api/v1/research/candidates",
        params={"workspace_id": workspace_id, "source_id": source_id},
    )
    assert listed.status_code == 200
    candidate_ids = [listed.json()["items"][0]["candidate_id"]]
    assert candidate_ids
    confirmed = client.post(
        "/api/v1/research/candidates/confirm",
        json={"workspace_id": workspace_id, "candidate_ids": candidate_ids},
        headers={"x-request-id": "req_slice5_confirm"},
    )
    assert confirmed.status_code == 200
    return candidate_ids


def _first_claim_id(workspace_id: str) -> str:
    claims = STORE.list_claims(workspace_id)
    assert claims
    return str(claims[0]["claim_id"])


def test_slice5_dev_console_exposes_graph_workspace_query_and_updates() -> None:
    client = _build_test_client()
    response = client.get("/api/v1/research/dev-console")
    assert response.status_code == 200
    assert "Graph Workspace" in response.text
    assert "Graph Query" in response.text
    assert "Graph Node Create / Update" in response.text
    assert "Graph Edge Create / Update" in response.text
    assert "/api/v1/research/graph/" in response.text


def test_slice5_graph_build_query_and_update_flow() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice5_api"
    _import_extract_confirm(
        client,
        workspace_id=workspace_id,
        content="Claim: graph build from confirmed objects. Assumption: local subgraph queries matter.",
    )

    prebuilt_versions = client.get(
        "/api/v1/research/versions", params={"workspace_id": workspace_id}
    )
    assert prebuilt_versions.status_code == 200
    assert prebuilt_versions.json()["items"]

    built = client.post(
        f"/api/v1/research/graph/{workspace_id}/build",
        headers={"x-request-id": "req_slice5_build"},
    )
    assert built.status_code == 200
    build_payload = built.json()
    assert build_payload["workspace_id"] == workspace_id
    assert build_payload["version_id"]
    assert build_payload["node_count"] >= 1
    assert build_payload["edge_count"] >= 0

    graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    assert graph.status_code == 200
    graph_payload = graph.json()
    assert graph_payload["nodes"]
    claim_id = str(graph_payload["nodes"][0]["claim_id"])
    assert all(node["object_ref_type"] for node in graph_payload["nodes"])
    assert all(node["object_ref_id"] for node in graph_payload["nodes"])
    assert all(edge["object_ref_type"] for edge in graph_payload["edges"])
    assert all(edge["object_ref_id"] for edge in graph_payload["edges"])

    center_node_id = graph_payload["nodes"][0]["node_id"]
    subgraph = client.post(
        f"/api/v1/research/graph/{workspace_id}/query",
        json={"center_node_id": center_node_id, "max_hops": 1},
    )
    assert subgraph.status_code == 200
    assert subgraph.json()["nodes"]
    if not subgraph.json()["edges"]:
        target_node_id = None
        if len(graph_payload["nodes"]) >= 2:
            target_node_id = graph_payload["nodes"][1]["node_id"]
        else:
            extra_node = client.post(
                "/api/v1/research/graph/nodes",
                json={
                    "workspace_id": workspace_id,
                    "node_type": "assumption",
                    "object_ref_type": "manual_note",
                    "object_ref_id": "slice5_manual_edge_target",
                    "short_label": "Slice5 Manual Edge Target",
                    "full_description": "manual node to enable edge update path",
                    "claim_id": claim_id,
                },
            )
            assert extra_node.status_code == 200
            target_node_id = extra_node.json()["node_id"]
        created_edge = client.post(
            "/api/v1/research/graph/edges",
            json={
                "workspace_id": workspace_id,
                "source_node_id": center_node_id,
                "target_node_id": target_node_id,
                "edge_type": "supports",
                "object_ref_type": "manual_link",
                "object_ref_id": "slice5_manual_edge",
                "strength": 0.8,
                "claim_id": claim_id,
            },
        )
        assert created_edge.status_code == 200
        subgraph = client.post(
            f"/api/v1/research/graph/{workspace_id}/query",
            json={"center_node_id": center_node_id, "max_hops": 1},
        )
        assert subgraph.status_code == 200
        assert subgraph.json()["edges"]

    updated_node = client.patch(
        f"/api/v1/research/graph/nodes/{center_node_id}",
        json={
            "workspace_id": workspace_id,
            "short_label": "Slice5 Updated Label",
            "status": "weakened",
        },
        headers={"x-request-id": "req_slice5_node_update"},
    )
    assert updated_node.status_code == 200

    requery = client.post(
        f"/api/v1/research/graph/{workspace_id}/query",
        json={"center_node_id": center_node_id, "max_hops": 1},
    )
    assert requery.status_code == 200
    center_after = next(
        node for node in requery.json()["nodes"] if node["node_id"] == center_node_id
    )
    assert center_after["short_label"] == "Slice5 Updated Label"
    assert center_after["status"] == "weakened"

    edge_id = requery.json()["edges"][0]["edge_id"]
    updated_edge = client.patch(
        f"/api/v1/research/graph/edges/{edge_id}",
        json={"workspace_id": workspace_id, "status": "weakened", "strength": 0.3},
        headers={"x-request-id": "req_slice5_edge_update"},
    )
    assert updated_edge.status_code == 200

    requery_after_edge_update = client.post(
        f"/api/v1/research/graph/{workspace_id}/query",
        json={"center_node_id": center_node_id, "max_hops": 1},
    )
    assert requery_after_edge_update.status_code == 200
    edge_after = next(
        edge
        for edge in requery_after_edge_update.json()["edges"]
        if edge["edge_id"] == edge_id
    )
    assert edge_after["status"] == "weakened"
    assert edge_after["strength"] == 0.3

    workspace_view = client.get(f"/api/v1/research/graph/{workspace_id}/workspace")
    assert workspace_view.status_code == 200
    assert workspace_view.json()["workspace_id"] == workspace_id
    assert workspace_view.json()["latest_version_id"] == build_payload["version_id"]

    with sqlite3.connect(STORE.db_path) as conn:
        version_row = conn.execute(
            "SELECT COUNT(*) FROM graph_versions WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        event_row = conn.execute(
            """
            SELECT COUNT(*)
            FROM research_events
            WHERE workspace_id = ?
              AND event_name IN ('graph_build_completed', 'graph_query_completed', 'graph_node_updated', 'graph_edge_updated')
            """,
            (workspace_id,),
        ).fetchone()
    assert version_row is not None and version_row[0] >= 1
    assert event_row is not None and event_row[0] >= 4


def test_slice5_graph_insight_endpoints_return_explicit_sections() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice5_insights"
    _import_extract_confirm(
        client,
        workspace_id=workspace_id,
        content="Claim: manual graph insight objects are claim-backed.",
    )
    claim_id = _first_claim_id(workspace_id)
    first = client.post(
        "/api/v1/research/graph/nodes",
        json={
            "workspace_id": workspace_id,
            "node_type": "evidence",
            "object_ref_type": "manual_note",
            "object_ref_id": "insight_evidence",
            "short_label": "Evidence",
            "full_description": "Evidence supports conclusion.",
            "claim_id": claim_id,
        },
    )
    second = client.post(
        "/api/v1/research/graph/nodes",
        json={
            "workspace_id": workspace_id,
            "node_type": "conclusion",
            "object_ref_type": "manual_note",
            "object_ref_id": "insight_conclusion",
            "short_label": "Conclusion",
            "full_description": "Conclusion under review.",
            "claim_id": claim_id,
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200
    evidence_node_id = first.json()["node_id"]
    conclusion_node_id = second.json()["node_id"]
    edge = client.post(
        "/api/v1/research/graph/edges",
        json={
            "workspace_id": workspace_id,
            "source_node_id": evidence_node_id,
            "target_node_id": conclusion_node_id,
            "edge_type": "supports",
            "object_ref_type": "manual_link",
            "object_ref_id": "insight_supports",
            "strength": 0.9,
            "claim_id": claim_id,
        },
    )
    assert edge.status_code == 200

    support = client.post(
        f"/api/v1/research/graph/{workspace_id}/support-chains",
        json={"workspace_id": workspace_id, "conclusion_node_id": conclusion_node_id},
    )
    predicted = client.post(
        f"/api/v1/research/graph/{workspace_id}/predicted-links",
        json={"workspace_id": workspace_id, "node_id": conclusion_node_id},
    )
    deep = client.post(
        f"/api/v1/research/graph/{workspace_id}/deep-chains",
        json={"workspace_id": workspace_id, "node_id": conclusion_node_id},
    )

    assert support.status_code == 200
    assert predicted.status_code == 200
    assert deep.status_code == 200
    assert "support_chains" in support.json()
    assert "predicted_links" in predicted.json()
    assert "deep_chains" in deep.json()


def test_slice5_workspace_validation_and_error_semantics() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice5_error"
    _import_extract_confirm(
        client,
        workspace_id=workspace_id,
        content="Claim: workspace and object back-reference checks are strict.",
    )
    built = client.post(f"/api/v1/research/graph/{workspace_id}/build")
    assert built.status_code == 200
    node_id = client.get(f"/api/v1/research/graph/{workspace_id}").json()["nodes"][0][
        "node_id"
    ]

    wrong_workspace = client.patch(
        f"/api/v1/research/graph/nodes/{node_id}",
        json={"workspace_id": "ws_other", "short_label": "x"},
    )
    assert wrong_workspace.status_code == 409
    assert wrong_workspace.json()["detail"]["error_code"] == "research.conflict"

    invalid_status = client.patch(
        f"/api/v1/research/graph/nodes/{node_id}",
        json={"workspace_id": workspace_id, "status": "invalid_status"},
    )
    assert invalid_status.status_code == 400
    assert invalid_status.json()["detail"]["error_code"] == "research.invalid_request"

    missing_node = client.patch(
        "/api/v1/research/graph/nodes/node_missing",
        json={"workspace_id": workspace_id, "status": "weakened"},
    )
    assert missing_node.status_code == 404
    assert missing_node.json()["detail"]["error_code"] == "research.not_found"

    missing_edge = client.patch(
        "/api/v1/research/graph/edges/edge_missing",
        json={"workspace_id": workspace_id, "status": "weakened"},
    )
    assert missing_edge.status_code == 404
    assert missing_edge.json()["detail"]["error_code"] == "research.not_found"

    missing_workspace_query = client.post(
        f"/api/v1/research/graph/{workspace_id}/query", json={"max_hops": 1}
    )
    assert missing_workspace_query.status_code == 400
    assert (
        missing_workspace_query.json()["detail"]["error_code"]
        == "research.invalid_request"
    )

    invalid_workspace_graph = client.get("/api/v1/research/graph/ws")
    assert invalid_workspace_graph.status_code == 400
    assert (
        invalid_workspace_graph.json()["detail"]["error_code"]
        == "research.invalid_request"
    )

    missing_diff = client.get("/api/v1/research/versions/ver_missing/diff")
    assert missing_diff.status_code == 404
    assert missing_diff.json()["detail"]["error_code"] == "research.not_found"


def test_track2_archive_delete_semantics_are_persistent_and_traceable() -> None:
    client = _build_test_client()
    workspace_id = 'ws_track2_archive'
    _import_extract_confirm(
        client,
        workspace_id=workspace_id,
        content='Claim: archive-backed delete keeps traceability. Assumption: archived objects remain queryable by status.',
    )

    built = client.post(f'/api/v1/research/graph/{workspace_id}/build')
    assert built.status_code == 200
    graph_before = client.get(f'/api/v1/research/graph/{workspace_id}')
    assert graph_before.status_code == 200
    node_before = graph_before.json()['nodes'][0]
    claim_id = str(node_before['claim_id'])
    if not graph_before.json()['edges']:
        if len(graph_before.json()['nodes']) == 1:
            created_node = client.post(
                '/api/v1/research/graph/nodes',
                json={
                    'workspace_id': workspace_id,
                    'node_type': 'assumption',
                    'object_ref_type': 'manual_note',
                    'object_ref_id': 'archive_manual_node',
                    'short_label': 'Archive Manual Node',
                    'full_description': 'manual node to satisfy archive edge path',
                    'claim_id': claim_id,
                },
            )
            assert created_node.status_code == 200
            graph_before = client.get(f'/api/v1/research/graph/{workspace_id}')
            assert graph_before.status_code == 200
        created_edge = client.post(
            '/api/v1/research/graph/edges',
            json={
                'workspace_id': workspace_id,
                'source_node_id': graph_before.json()['nodes'][0]['node_id'],
                'target_node_id': graph_before.json()['nodes'][1]['node_id'],
                'edge_type': 'supports',
                'object_ref_type': 'manual_link',
                'object_ref_id': 'archive_manual_edge',
                'strength': 0.7,
                'claim_id': claim_id,
            },
        )
        assert created_edge.status_code == 200
        graph_before = client.get(f'/api/v1/research/graph/{workspace_id}')
        assert graph_before.status_code == 200
    edge_before = graph_before.json()['edges'][0]
    node_id = node_before['node_id']
    edge_id = edge_before['edge_id']
    node_ref = (node_before['object_ref_type'], node_before['object_ref_id'])
    edge_ref = (edge_before['object_ref_type'], edge_before['object_ref_id'])

    archive_node = client.request(
        'DELETE',
        f'/api/v1/research/graph/nodes/{node_id}',
        json={'workspace_id': workspace_id, 'reason': 'workbench delete node'},
        headers={'x-request-id': 'req_track2_archive_node'},
    )
    assert archive_node.status_code == 200
    node_payload = archive_node.json()
    assert node_payload['status'] == 'archived'
    assert node_payload['target_type'] == 'node'
    assert node_payload['target_id'] == node_id
    assert node_id in node_payload['diff_payload']['archived']['nodes']

    archive_edge = client.request(
        'DELETE',
        f'/api/v1/research/graph/edges/{edge_id}',
        json={'workspace_id': workspace_id, 'reason': 'workbench delete edge'},
        headers={'x-request-id': 'req_track2_archive_edge'},
    )
    assert archive_edge.status_code == 200
    edge_payload = archive_edge.json()
    assert edge_payload['status'] == 'archived'
    assert edge_payload['target_type'] == 'edge'
    assert edge_payload['target_id'] == edge_id
    assert edge_id in edge_payload['diff_payload']['archived']['edges']

    node_version_id = node_payload['version_id']
    edge_version_id = edge_payload['version_id']
    node_diff = client.get(f'/api/v1/research/versions/{node_version_id}/diff')
    edge_diff = client.get(f'/api/v1/research/versions/{edge_version_id}/diff')
    assert node_diff.status_code == 200
    assert edge_diff.status_code == 200
    assert node_id in node_diff.json()['diff_payload']['archived']['nodes']
    assert edge_id in edge_diff.json()['diff_payload']['archived']['edges']

    graph_after = client.get(f'/api/v1/research/graph/{workspace_id}')
    assert graph_after.status_code == 200
    node_after = next(
        node for node in graph_after.json()['nodes'] if node['node_id'] == node_id
    )
    edge_after = next(
        edge for edge in graph_after.json()['edges'] if edge['edge_id'] == edge_id
    )
    assert node_after['status'] == 'archived'
    assert edge_after['status'] == 'archived'

    revive_archived_node = client.patch(
        f'/api/v1/research/graph/nodes/{node_id}',
        json={'workspace_id': workspace_id, 'status': 'active'},
    )
    assert revive_archived_node.status_code == 409
    assert (
        revive_archived_node.json()['detail']['error_code'] == 'research.invalid_state'
    )

    revive_archived_edge = client.patch(
        f'/api/v1/research/graph/edges/{edge_id}',
        json={'workspace_id': workspace_id, 'status': 'active'},
    )
    assert revive_archived_edge.status_code == 409
    assert (
        revive_archived_edge.json()['detail']['error_code'] == 'research.invalid_state'
    )

    rebuild = client.post(
        f'/api/v1/research/graph/{workspace_id}/build',
        headers={'x-request-id': 'req_track2_archive_rebuild'},
    )
    assert rebuild.status_code == 200
    graph_after_rebuild = client.get(f'/api/v1/research/graph/{workspace_id}')
    assert graph_after_rebuild.status_code == 200
    matching_nodes = [
        node
        for node in graph_after_rebuild.json()['nodes']
        if (node['object_ref_type'], node['object_ref_id']) == node_ref
    ]
    matching_edges = [
        edge
        for edge in graph_after_rebuild.json()['edges']
        if (edge['object_ref_type'], edge['object_ref_id']) == edge_ref
    ]
    assert matching_nodes and any(
        node['status'] == 'archived' for node in matching_nodes
    )
    assert matching_edges and any(
        edge['status'] == 'archived' for edge in matching_edges
    )

    duplicate_archive_edge = client.request(
        'DELETE',
        f'/api/v1/research/graph/edges/{edge_id}',
        json={'workspace_id': workspace_id},
    )
    assert duplicate_archive_edge.status_code == 409
    assert (
        duplicate_archive_edge.json()['detail']['error_code']
        == 'research.invalid_state'
    )


def _assert_invalid_request_response(response, *, reason_fragment: str) -> None:
    assert response.status_code == 400
    payload = response.json()["detail"]
    assert payload["error_code"] == "research.invalid_request"
    assert payload["message"] == "request validation failed"
    assert "errors" in payload["details"]
    serialized = str(payload["details"]["errors"])
    assert reason_fragment in serialized


def test_slice5_graph_write_endpoints_convert_invalid_request_bodies_into_explicit_400() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice5_invalid_bodies"
    _import_extract_confirm(
        client,
        workspace_id=workspace_id,
        content="Claim: graph endpoints should reject invalid bodies explicitly.",
    )
    built = client.post(f"/api/v1/research/graph/{workspace_id}/build")
    assert built.status_code == 200
    graph_payload = client.get(f"/api/v1/research/graph/{workspace_id}").json()
    node_id = graph_payload["nodes"][0]["node_id"]
    claim_id = str(graph_payload["nodes"][0]["claim_id"])
    if not graph_payload["edges"]:
        if len(graph_payload["nodes"]) < 2:
            created_node = client.post(
                "/api/v1/research/graph/nodes",
                json={
                    "workspace_id": workspace_id,
                    "node_type": "assumption",
                    "object_ref_type": "manual_note",
                    "object_ref_id": "node_invalid_body_seed",
                    "short_label": "Manual Seed Node",
                    "full_description": "Seed node for edge invalid body regression.",
                    "claim_id": claim_id,
                },
            )
            assert created_node.status_code == 200
            graph_payload = client.get(f"/api/v1/research/graph/{workspace_id}").json()
        created_edge = client.post(
            "/api/v1/research/graph/edges",
            json={
                "workspace_id": workspace_id,
                "source_node_id": graph_payload["nodes"][0]["node_id"],
                "target_node_id": graph_payload["nodes"][1]["node_id"],
                "edge_type": "supports",
                "object_ref_type": "manual_link",
                "object_ref_id": "edge_invalid_body_seed",
                "strength": 0.8,
                "claim_id": claim_id,
            },
        )
        assert created_edge.status_code == 200
        edge_id = created_edge.json()["edge_id"]
    else:
        edge_id = graph_payload["edges"][0]["edge_id"]
    center_node_id = node_id

    endpoints = [
        (
            "query",
            "POST",
            f"/api/v1/research/graph/{workspace_id}/query",
            {"center_node_id": center_node_id, "max_hops": 1},
        ),
        (
            "node_patch",
            "PATCH",
            f"/api/v1/research/graph/nodes/{node_id}",
            {"workspace_id": workspace_id, "status": "weakened"},
        ),
        (
            "edge_patch",
            "PATCH",
            f"/api/v1/research/graph/edges/{edge_id}",
            {"workspace_id": workspace_id, "status": "weakened"},
        ),
        (
            "node_delete",
            "DELETE",
            f"/api/v1/research/graph/nodes/{node_id}",
            {"workspace_id": workspace_id, "reason": "invalid body regression"},
        ),
        (
            "edge_delete",
            "DELETE",
            f"/api/v1/research/graph/edges/{edge_id}",
            {"workspace_id": workspace_id, "reason": "invalid body regression"},
        ),
    ]

    for _, method, url, valid_payload in endpoints:
        empty_response = client.request(method, url)
        _assert_invalid_request_response(
            empty_response, reason_fragment="empty request body"
        )

        bad_json_response = client.request(
            method,
            url,
            data="{bad",
            headers={"Content-Type": "application/json"},
        )
        _assert_invalid_request_response(
            bad_json_response, reason_fragment="invalid json body"
        )

        for raw_payload in ["[]", '"abc"', "123", "true"]:
            non_object_response = client.request(
                method,
                url,
                data=raw_payload,
                headers={"Content-Type": "application/json"},
            )
            _assert_invalid_request_response(
                non_object_response, reason_fragment="JSON object"
            )

        if "workspace_id" in valid_payload:
            missing_workspace_response = client.request(
                method,
                url,
                json={
                    key: value
                    for key, value in valid_payload.items()
                    if key != "workspace_id"
                },
            )
            _assert_invalid_request_response(
                missing_workspace_response, reason_fragment="workspace_id"
            )


def test_slice5_graph_manual_create_requires_claim_id() -> None:
    client = _build_test_client()

    response = client.post(
        "/api/v1/research/graph/nodes",
        json={
            "workspace_id": "ws_manual_claim_gate",
            "node_type": "claim",
            "object_ref_type": "manual_note",
            "object_ref_id": "manual_1",
            "short_label": "Manual node",
            "full_description": "Manual graph writes must bind a claim.",
        },
    )

    payload = response.json().get("detail", response.json())
    assert response.status_code == 400
    assert payload["error_code"] == "research.invalid_request"
    assert payload["details"]["reason"] == "missing_claim_id"


def test_slice5_graph_manual_create_rejects_unknown_claim_id() -> None:
    client = _build_test_client()

    response = client.post(
        "/api/v1/research/graph/nodes",
        json={
            "workspace_id": "ws_manual_claim_gate",
            "node_type": "claim",
            "object_ref_type": "manual_note",
            "object_ref_id": "manual_unknown_claim",
            "short_label": "Manual node",
            "full_description": "Manual graph writes must bind an existing claim.",
            "claim_id": "claim_missing",
        },
    )

    payload = response.json().get("detail", response.json())
    assert response.status_code == 400
    assert payload["error_code"] == "research.invalid_request"
    assert payload["details"]["reason"] == "claim_not_found"


def test_slice5_graph_manual_edge_create_requires_claim_id() -> None:
    client = _build_test_client()
    workspace_id = "ws_manual_edge_claim_gate"
    _import_extract_confirm(
        client,
        workspace_id=workspace_id,
        content="Claim: manual edge projections require claim provenance.",
    )
    claim_id = _first_claim_id(workspace_id)
    first = client.post(
        "/api/v1/research/graph/nodes",
        json={
            "workspace_id": workspace_id,
            "node_type": "claim",
            "object_ref_type": "manual_note",
            "object_ref_id": "manual_edge_gate_1",
            "short_label": "Manual edge gate 1",
            "full_description": "Manual edge source.",
            "claim_id": claim_id,
        },
    )
    second = client.post(
        "/api/v1/research/graph/nodes",
        json={
            "workspace_id": workspace_id,
            "node_type": "claim",
            "object_ref_type": "manual_note",
            "object_ref_id": "manual_edge_gate_2",
            "short_label": "Manual edge gate 2",
            "full_description": "Manual edge target.",
            "claim_id": claim_id,
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200

    response = client.post(
        "/api/v1/research/graph/edges",
        json={
            "workspace_id": workspace_id,
            "source_node_id": first.json()["node_id"],
            "target_node_id": second.json()["node_id"],
            "edge_type": "supports",
            "object_ref_type": "manual_link",
            "object_ref_id": "manual_edge_missing_claim",
            "strength": 0.8,
        },
    )

    payload = response.json().get("detail", response.json())
    assert response.status_code == 400
    assert payload["error_code"] == "research.invalid_request"
    assert payload["details"]["reason"] == "missing_claim_id"


def test_slice5_graph_manual_edge_create_rejects_cross_workspace_claim_id() -> None:
    client = _build_test_client()
    owner_workspace_id = "ws_manual_edge_claim_owner"
    edge_workspace_id = "ws_manual_edge_claim_other"
    _import_extract_confirm(
        client,
        workspace_id=owner_workspace_id,
        content="Claim: this claim belongs to another workspace.",
    )
    foreign_claim_id = _first_claim_id(owner_workspace_id)
    _import_extract_confirm(
        client,
        workspace_id=edge_workspace_id,
        content="Claim: manual edge endpoints belong to this workspace.",
    )
    local_claim_id = _first_claim_id(edge_workspace_id)
    first = client.post(
        "/api/v1/research/graph/nodes",
        json={
            "workspace_id": edge_workspace_id,
            "node_type": "claim",
            "object_ref_type": "manual_note",
            "object_ref_id": "manual_cross_edge_1",
            "short_label": "Manual cross edge 1",
            "full_description": "Manual edge source.",
            "claim_id": local_claim_id,
        },
    )
    second = client.post(
        "/api/v1/research/graph/nodes",
        json={
            "workspace_id": edge_workspace_id,
            "node_type": "claim",
            "object_ref_type": "manual_note",
            "object_ref_id": "manual_cross_edge_2",
            "short_label": "Manual cross edge 2",
            "full_description": "Manual edge target.",
            "claim_id": local_claim_id,
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200

    response = client.post(
        "/api/v1/research/graph/edges",
        json={
            "workspace_id": edge_workspace_id,
            "source_node_id": first.json()["node_id"],
            "target_node_id": second.json()["node_id"],
            "edge_type": "supports",
            "object_ref_type": "manual_link",
            "object_ref_id": "manual_edge_cross_workspace_claim",
            "strength": 0.8,
            "claim_id": foreign_claim_id,
        },
    )

    payload = response.json().get("detail", response.json())
    assert response.status_code == 400
    assert payload["error_code"] == "research.invalid_request"
    assert payload["details"]["reason"] == "claim_workspace_mismatch"


def test_slice5_graph_manual_create_writes_claim_source_ref() -> None:
    client = _build_test_client()
    workspace_id = "ws_manual_claim_source_ref"
    _import_extract_confirm(
        client,
        workspace_id=workspace_id,
        content="Claim: manual graph projections retain source provenance.",
    )
    claim_id = _first_claim_id(workspace_id)

    first = client.post(
        "/api/v1/research/graph/nodes",
        json={
            "workspace_id": workspace_id,
            "node_type": "claim",
            "object_ref_type": "manual_note",
            "object_ref_id": "manual_source_ref_1",
            "short_label": "Manual source ref 1",
            "full_description": "Manual node with claim provenance.",
            "claim_id": claim_id,
        },
    )
    second = client.post(
        "/api/v1/research/graph/nodes",
        json={
            "workspace_id": workspace_id,
            "node_type": "claim",
            "object_ref_type": "manual_note",
            "object_ref_id": "manual_source_ref_2",
            "short_label": "Manual source ref 2",
            "full_description": "Second manual node with claim provenance.",
            "claim_id": claim_id,
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200
    node_payload = first.json()
    assert node_payload["claim_id"] == claim_id
    assert node_payload["source_ref"]["claim_id"] == claim_id
    assert {"source_id", "source_span", "trace_refs"} <= set(node_payload["source_ref"])

    edge = client.post(
        "/api/v1/research/graph/edges",
        json={
            "workspace_id": workspace_id,
            "source_node_id": first.json()["node_id"],
            "target_node_id": second.json()["node_id"],
            "edge_type": "supports",
            "object_ref_type": "manual_link",
            "object_ref_id": "manual_source_ref_edge",
            "strength": 0.8,
            "claim_id": claim_id,
        },
    )
    assert edge.status_code == 200
    edge_payload = edge.json()
    assert edge_payload["claim_id"] == claim_id
    assert edge_payload["source_ref"]["claim_id"] == claim_id
    assert {"source_id", "source_span", "trace_refs"} <= set(edge_payload["source_ref"])
