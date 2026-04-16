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
from research_layer.api.controllers.research_retrieval_controller import (
    ResearchRetrievalController,
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
        ResearchRetrievalController(),
        ResearchPackageController(),
        ResearchJobController(),
    ]
    for controller in controllers:
        controller.register_to_app(app)
    return TestClient(app)


def _seed_slice11_workspace(workspace_id: str) -> dict[str, str]:
    validation = STORE.create_validation(
        workspace_id=workspace_id,
        target_object="route:seed",
        method="run deterministic benchmark",
        success_signal="support increases",
        weakening_signal="support decreases",
    )
    evidence_node = STORE.create_graph_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="research_evidence",
        object_ref_id="evidence_seed_01",
        short_label="Evidence seed",
        full_description="Seed evidence node for package integration tests",
        status="active",
    )
    private_node = STORE.create_graph_node(
        workspace_id=workspace_id,
        node_type="private_dependency",
        object_ref_type="private_note",
        object_ref_id="private_seed_01",
        short_label="Private dependency seed",
        full_description="Private dependency that must map to public gap",
        status="active",
    )
    validation_node = STORE.create_graph_node(
        workspace_id=workspace_id,
        node_type="validation",
        object_ref_type="validation_action",
        object_ref_id=str(validation["validation_id"]),
        short_label="Validation seed",
        full_description="Validation node linked to validation action",
        status="active",
    )
    route = STORE.create_route(
        workspace_id=workspace_id,
        title="Slice11 Route Seed",
        summary="route for package integration",
        status="active",
        support_score=0.8,
        risk_score=0.3,
        progressability_score=0.71,
        conclusion="Route conclusion",
        key_supports=["support evidence"],
        assumptions=["assumption"],
        risks=["risk"],
        next_validation_action="run deterministic benchmark",
        conclusion_node_id=str(evidence_node["node_id"]),
        route_node_ids=[
            str(evidence_node["node_id"]),
            str(private_node["node_id"]),
            str(validation_node["node_id"]),
        ],
        key_support_node_ids=[str(evidence_node["node_id"])],
        key_assumption_node_ids=[],
        risk_node_ids=[str(private_node["node_id"])],
        next_validation_node_id=str(validation_node["node_id"]),
        version_id="ver_slice11_seed",
    )
    return {
        "route_id": str(route["route_id"]),
        "private_node_id": str(private_node["node_id"]),
        "validation_id": str(validation["validation_id"]),
    }


def _seed_route_from_source_flow(client: TestClient, workspace_id: str) -> str:
    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": workspace_id,
            "source_type": "paper",
            "title": "slice11 route-only package seed",
            "content": (
                "Claim: retrieval precision improves with indexing. "
                "Assumption: cache remains warm. "
                "Conflict: latency may regress under load. "
                "Failure: timeout spikes on shard imbalance. "
                "Validation: run replay benchmark."
            ),
        },
        headers={"x-request-id": "req_slice11_route_only_import"},
    )
    assert imported.status_code == 200
    source_id = imported.json()["source_id"]

    extracted = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": workspace_id, "async_mode": True},
        headers={
            "x-request-id": "req_slice11_route_only_extract",
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert extracted.status_code == 202
    extract_job = wait_for_job_terminal(
        client, job_id=str(extracted.json()["job_id"])
    )
    assert extract_job["status"] == "succeeded"

    candidates = client.get(
        "/api/v1/research/candidates",
        params={"workspace_id": workspace_id, "source_id": source_id},
    )
    assert candidates.status_code == 200
    candidate_ids = [item["candidate_id"] for item in candidates.json()["items"]]
    assert candidate_ids

    confirmed_count = 0
    for candidate_id in candidate_ids:
        confirmed = client.post(
            "/api/v1/research/candidates/confirm",
            json={"workspace_id": workspace_id, "candidate_ids": [candidate_id]},
            headers={"x-request-id": f"req_slice11_route_only_confirm_{candidate_id}"},
        )
        if confirmed.status_code == 200:
            confirmed_count += 1
            continue
        assert confirmed.status_code == 409, confirmed.text
    assert confirmed_count > 0

    graph_built = client.post(
        f"/api/v1/research/graph/{workspace_id}/build",
        headers={"x-request-id": "req_slice11_route_only_graph_build"},
    )
    assert graph_built.status_code == 200

    generated = client.post(
        "/api/v1/research/routes/generate",
        json={
            "workspace_id": workspace_id,
            "reason": "seed route for package route-only flow",
            "max_candidates": 8,
        },
        headers={
            "x-request-id": "req_slice11_route_only_generate",
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert generated.status_code == 200
    route_ids = generated.json()["ranked_route_ids"]
    assert route_ids
    return route_ids[0]


def test_slice11_dev_console_exposes_package_controls() -> None:
    client = _build_test_client()
    response = client.get("/api/v1/research/dev-console")
    assert response.status_code == 200
    assert "Research Package" in response.text
    assert "Create Package Snapshot" in response.text
    assert "Load Package Replay" in response.text
    assert "Publish Package" in response.text


def test_slice11_package_create_query_replay_publish_and_observability() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice11_package_flow"
    seeded = _seed_slice11_workspace(workspace_id)

    created = client.post(
        "/api/v1/research/packages",
        json={
            "workspace_id": workspace_id,
            "title": "Slice11 package",
            "summary": "snapshot package for integration",
            "included_route_ids": [seeded["route_id"]],
            "included_node_ids": [],
            "included_validation_ids": [seeded["validation_id"]],
        },
        headers={"x-request-id": "req_slice11_create"},
    )
    assert created.status_code == 200
    created_payload = created.json()
    package_id = created_payload["package_id"]
    assert created_payload["workspace_id"] == workspace_id
    assert created_payload["snapshot_type"] == "research_package_snapshot"
    assert created_payload["snapshot_version"] == "slice11.v1"
    assert created_payload["replay_ready"] is True
    assert created_payload["private_dependency_flags"]
    assert created_payload["public_gap_nodes"]
    assert seeded["private_node_id"] not in created_payload["included_node_ids"]
    assert created_payload["private_dependency_flags"][0]["replacement_gap_node_id"] == created_payload["public_gap_nodes"][0]["node_id"]

    queried = client.get("/api/v1/research/packages", params={"workspace_id": workspace_id})
    assert queried.status_code == 200
    assert queried.json()["total"] >= 1
    assert any(item["package_id"] == package_id for item in queried.json()["items"])

    loaded = client.get(
        f"/api/v1/research/packages/{package_id}",
        params={"workspace_id": workspace_id},
    )
    assert loaded.status_code == 200
    assert loaded.json()["package_id"] == package_id

    replay = client.get(
        f"/api/v1/research/packages/{package_id}/replay",
        params={"workspace_id": workspace_id},
    )
    assert replay.status_code == 200
    replay_payload = replay.json()
    assert replay_payload["package_id"] == package_id
    assert replay_payload["snapshot"]["routes"]
    assert replay_payload["snapshot"]["nodes"]
    assert replay_payload["snapshot"]["validations"]
    assert replay_payload["snapshot"]["private_dependency_flags"]
    assert replay_payload["snapshot"]["public_gap_nodes"]
    replacement_gap_node_id = replay_payload["snapshot"]["private_dependency_flags"][0][
        "replacement_gap_node_id"
    ]
    replay_route = replay_payload["snapshot"]["routes"][0]
    assert seeded["private_node_id"] not in replay_route["route_node_ids"]
    assert replacement_gap_node_id in replay_route["route_node_ids"]
    replacement_map = replay_payload["snapshot"]["traceability_refs"]["replacement_map"]
    assert replacement_map[seeded["private_node_id"]] == replacement_gap_node_id

    publish = client.post(
        f"/api/v1/research/packages/{package_id}/publish",
        json={"workspace_id": workspace_id, "async_mode": True},
        headers={"x-request-id": "req_slice11_publish"},
    )
    assert publish.status_code == 202
    publish_payload = publish.json()
    job_id = publish_payload["job_id"]

    job = client.get(f"/api/v1/research/jobs/{job_id}")
    assert job.status_code == 200
    job_payload = wait_for_job_terminal(client, job_id=job_id)
    assert job_payload["status"] == "succeeded"
    assert job_payload["result_ref"]["resource_type"] == "package_publish_result"
    publish_result_id = job_payload["result_ref"]["resource_id"]

    publish_result = client.get(
        f"/api/v1/research/packages/{package_id}/publish-results/{publish_result_id}",
        params={"workspace_id": workspace_id},
    )
    assert publish_result.status_code == 200
    assert publish_result.json()["publish_result_id"] == publish_result_id
    assert publish_result.json()["package_id"] == package_id
    assert publish_result.json()["workspace_id"] == workspace_id

    with sqlite3.connect(STORE.db_path) as conn:
        events = conn.execute(
            """
            SELECT event_name, status, COUNT(*)
            FROM research_events
            WHERE workspace_id = ?
              AND event_name IN (
                'package_build_started',
                'package_build_completed',
                'package_publish_started',
                'package_publish_completed'
              )
            GROUP BY event_name, status
            """,
            (workspace_id,),
        ).fetchall()
    event_counter = {(row[0], row[1]): row[2] for row in events}
    assert event_counter.get(("package_build_started", "started"), 0) >= 1
    assert event_counter.get(("package_build_completed", "completed"), 0) >= 1
    assert event_counter.get(("package_publish_started", "started"), 0) >= 1
    assert event_counter.get(("package_publish_completed", "completed"), 0) >= 1


def test_slice11_package_errors_for_invalid_input_conflict_and_invalid_state() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice11_package_errors"
    seeded = _seed_slice11_workspace(workspace_id)

    empty_create = client.post(
        "/api/v1/research/packages",
        json={
            "workspace_id": workspace_id,
            "title": "invalid",
            "summary": "empty package request",
            "included_route_ids": [],
            "included_node_ids": [],
            "included_validation_ids": [],
        },
    )
    assert empty_create.status_code == 400
    assert empty_create.json()["detail"]["error_code"] == "research.invalid_request"

    missing_route_create = client.post(
        "/api/v1/research/packages",
        json={
            "workspace_id": workspace_id,
            "title": "missing route",
            "summary": "invalid route",
            "included_route_ids": ["route_missing"],
            "included_node_ids": [],
            "included_validation_ids": [],
        },
    )
    assert missing_route_create.status_code == 404
    assert missing_route_create.json()["detail"]["error_code"] == "research.not_found"

    created = client.post(
        "/api/v1/research/packages",
        json={
            "workspace_id": workspace_id,
            "title": "valid package",
            "summary": "for conflict checks",
            "included_route_ids": [seeded["route_id"]],
            "included_node_ids": [],
            "included_validation_ids": [seeded["validation_id"]],
        },
    )
    assert created.status_code == 200
    package_id = created.json()["package_id"]

    conflict_get = client.get(
        f"/api/v1/research/packages/{package_id}",
        params={"workspace_id": "ws_other_workspace"},
    )
    assert conflict_get.status_code == 409
    assert conflict_get.json()["detail"]["error_code"] == "research.conflict"

    conflict_publish = client.post(
        f"/api/v1/research/packages/{package_id}/publish",
        json={"workspace_id": "ws_other_workspace", "async_mode": True},
    )
    assert conflict_publish.status_code == 409
    assert conflict_publish.json()["detail"]["error_code"] == "research.conflict"

    first_publish = client.post(
        f"/api/v1/research/packages/{package_id}/publish",
        json={"workspace_id": workspace_id, "async_mode": True},
    )
    assert first_publish.status_code == 202
    first_job = wait_for_job_terminal(
        client, job_id=str(first_publish.json()["job_id"])
    )
    assert first_job["status"] == "succeeded"
    second_publish = client.post(
        f"/api/v1/research/packages/{package_id}/publish",
        json={"workspace_id": workspace_id, "async_mode": True},
    )
    assert second_publish.status_code == 409
    assert second_publish.json()["detail"]["error_code"] == "research.invalid_state"


def test_slice11_package_create_with_route_only_survives_missing_route_derived_validation_refs() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice11_route_only_package"
    route_id = _seed_route_from_source_flow(client, workspace_id)

    created = client.post(
        "/api/v1/research/packages",
        json={
            "workspace_id": workspace_id,
            "title": "Slice11 route-only package",
            "summary": "ensure route-derived validation gaps do not block package build",
            "included_route_ids": [route_id],
            "included_node_ids": [],
            "included_validation_ids": [],
        },
        headers={"x-request-id": "req_slice11_route_only_package_create"},
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["included_route_ids"] == [route_id]
    assert payload["package_id"]
    assert payload["traceability_refs"]["routes"][route_id]["node_ids"]
    assert "missing_route_validation_ids" in payload["traceability_refs"]


def _assert_invalid_request_response(response, *, reason_fragment: str) -> None:
    assert response.status_code == 400
    payload = response.json()["detail"]
    assert payload["error_code"] == "research.invalid_request"
    assert payload["message"] == "request validation failed"
    assert "errors" in payload["details"]
    serialized = str(payload["details"]["errors"])
    assert reason_fragment in serialized


def test_slice11_package_publish_rejects_async_mode_false() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice11_publish_async_false"
    seeded = _seed_slice11_workspace(workspace_id)
    created = client.post(
        "/api/v1/research/packages",
        json={
            "workspace_id": workspace_id,
            "title": "async false package",
            "summary": "enforce async contract",
            "included_route_ids": [seeded["route_id"]],
            "included_node_ids": [],
            "included_validation_ids": [seeded["validation_id"]],
        },
    )
    assert created.status_code == 200
    package_id = created.json()["package_id"]

    publish = client.post(
        f"/api/v1/research/packages/{package_id}/publish",
        json={"workspace_id": workspace_id, "async_mode": False},
        headers={"x-request-id": "req_slice11_publish_async_false"},
    )
    assert publish.status_code == 400
    detail = publish.json()["detail"]
    assert detail["error_code"] == "research.invalid_request"
    assert "async_mode must be true" in detail["message"]


def test_slice11_package_publish_failure_marks_job_failed_with_explicit_error() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice11_publish_fail_job"
    seeded = _seed_slice11_workspace(workspace_id)
    created = client.post(
        "/api/v1/research/packages",
        json={
            "workspace_id": workspace_id,
            "title": "publish failure package",
            "summary": "force publish insert constraint failure",
            "included_route_ids": [seeded["route_id"]],
            "included_node_ids": [],
            "included_validation_ids": [seeded["validation_id"]],
        },
        headers={"x-request-id": "req_slice11_publish_fail_create"},
    )
    assert created.status_code == 200
    package_id = created.json()["package_id"]

    with sqlite3.connect(STORE.db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS package_publish_results")
        conn.commit()

    try:
        publish = client.post(
            f"/api/v1/research/packages/{package_id}/publish",
            json={"workspace_id": workspace_id, "async_mode": True},
            headers={"x-request-id": "req_slice11_publish_fail_publish"},
        )
        assert publish.status_code == 202
        job_payload = wait_for_job_terminal(client, job_id=str(publish.json()["job_id"]))
        assert job_payload["status"] == "failed"
        assert job_payload["error"]["error_code"] == "research.package_publish_failed"

        package = client.get(
            f"/api/v1/research/packages/{package_id}",
            params={"workspace_id": workspace_id},
        )
        assert package.status_code == 200
        assert package.json()["status"] == "draft"

        with sqlite3.connect(STORE.db_path) as conn:
            table_exists = conn.execute(
                """
                SELECT COUNT(*)
                FROM sqlite_master
                WHERE type='table' AND name='package_publish_results'
                """
            ).fetchone()
        assert table_exists is not None and table_exists[0] == 0
    finally:
        STORE._ensure_schema()


def test_slice11_package_write_endpoints_convert_invalid_request_bodies_into_explicit_400() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice11_invalid_bodies"
    seeded = _seed_slice11_workspace(workspace_id)
    created = client.post(
        "/api/v1/research/packages",
        json={
            "workspace_id": workspace_id,
            "title": "seed package",
            "summary": "seed summary",
            "included_route_ids": [seeded["route_id"]],
            "included_node_ids": [],
            "included_validation_ids": [seeded["validation_id"]],
        },
    )
    assert created.status_code == 200
    package_id = created.json()["package_id"]

    endpoints = [
        (
            "create",
            "POST",
            "/api/v1/research/packages",
            {
                "workspace_id": workspace_id,
                "title": "pkg",
                "summary": "sum",
                "included_route_ids": [seeded["route_id"]],
                "included_node_ids": [],
                "included_validation_ids": [seeded["validation_id"]],
            },
        ),
        (
            "publish",
            "POST",
            f"/api/v1/research/packages/{package_id}/publish",
            {"workspace_id": workspace_id, "async_mode": True},
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

        missing_workspace_response = client.request(
            method,
            url,
            json={key: value for key, value in valid_payload.items() if key != "workspace_id"},
        )
        _assert_invalid_request_response(
            missing_workspace_response, reason_fragment="workspace_id"
        )
