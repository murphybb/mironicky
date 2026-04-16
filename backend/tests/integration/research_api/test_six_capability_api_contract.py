from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.middleware.global_exception_handler import global_exception_handler
from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers.research_command_controller import (
    ResearchCommandController,
)
from research_layer.api.controllers.research_failure_controller import (
    ResearchFailureController,
)
from research_layer.api.controllers.research_graph_controller import (
    ResearchGraphController,
)
from research_layer.api.controllers.research_job_controller import ResearchJobController
from research_layer.api.controllers.research_package_controller import (
    ResearchPackageController,
)
from research_layer.api.controllers.research_query_controller import (
    ResearchQueryController,
)
from research_layer.api.controllers.research_route_controller import (
    ResearchRouteController,
)
from research_layer.api.controllers.research_source_controller import (
    ResearchSourceController,
)
from research_layer.services.graph_report_service import GraphReportService
from research_layer.testing.job_helpers import wait_for_job_terminal


def _build_client() -> TestClient:
    STORE.reset_all()
    app = FastAPI()
    app.add_exception_handler(HTTPException, global_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
    for controller in [
        ResearchSourceController(),
        ResearchGraphController(),
        ResearchRouteController(),
        ResearchFailureController(),
        ResearchPackageController(),
        ResearchJobController(),
        ResearchQueryController(),
        ResearchCommandController(),
    ]:
        controller.register_to_app(app)
    return TestClient(app, raise_server_exceptions=False)


def _enable_six_flags(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_FEATURE_GRAPH_REPORT_ENABLED", "1")
    monkeypatch.setenv("RESEARCH_FEATURE_QUERY_API_ENABLED", "1")
    monkeypatch.setenv("RESEARCH_FEATURE_RAW_BOOTSTRAP_ENABLED", "1")
    monkeypatch.setenv("RESEARCH_FEATURE_COMMANDS_ENABLED", "1")
    monkeypatch.setenv("RESEARCH_FEATURE_EXPORT_ENABLED", "1")


def test_six_capability_endpoints_are_feature_flagged_by_default() -> None:
    client = _build_client()

    response = client.get("/api/v1/research/query/tools")

    assert response.status_code == 403
    payload = response.json()
    assert payload["error_code"] == "research.forbidden"
    assert payload["details"]["feature_flag"] == "RESEARCH_FEATURE_QUERY_API_ENABLED"


def test_bootstrap_query_report_and_export_contract(monkeypatch) -> None:
    _enable_six_flags(monkeypatch)
    client = _build_client()
    workspace_id = "ws_six_api"

    bootstrap = client.post(
        "/api/v1/research/sources/bootstrap",
        json={
            "workspace_id": workspace_id,
            "run_extract": False,
            "materials": [
                {
                    "source_type": "paper",
                    "title": "contract paper",
                    "content": "Evidence: graph reports help. Assumption: export is safe.",
                    "candidates": [
                        {
                            "candidate_type": "evidence",
                            "text": "Evidence: graph reports help.",
                        },
                        {
                            "candidate_type": "assumption",
                            "text": "Assumption: export is safe.",
                        },
                    ],
                }
            ],
        },
    )
    assert bootstrap.status_code == 200
    bootstrap_payload = bootstrap.json()
    assert bootstrap_payload["imported_count"] == 1
    assert bootstrap_payload["failed_count"] == 0

    candidates = client.get(
        "/api/v1/research/candidates", params={"workspace_id": workspace_id}
    )
    assert candidates.status_code == 200
    candidate_ids = [item["candidate_id"] for item in candidates.json()["items"]]

    command = client.post(
        "/api/v1/research/commands/run",
        json={
            "workspace_id": workspace_id,
            "commands": [
                {"name": "confirm", "args": {"candidate_ids": candidate_ids}},
                {"name": "build_graph", "args": {}},
            ],
        },
    )
    assert command.status_code == 200
    assert [step["status"] for step in command.json()["steps"]] == ["succeeded", "succeeded"]

    report = client.get(f"/api/v1/research/graph/{workspace_id}/report")
    assert report.status_code == 200
    assert report.json()["summary"]["node_count"] >= 2

    tools = client.get("/api/v1/research/query/tools")
    assert tools.status_code == 200
    assert "report" in [tool["name"] for tool in tools.json()["tools"]]

    query = client.post(
        "/api/v1/research/query/run",
        json={"workspace_id": workspace_id, "tool_name": "report", "arguments": {}},
    )
    assert query.status_code == 200
    assert query.json()["result"]["summary"]["node_count"] >= 2

    exported = client.get(
        f"/api/v1/research/graph/{workspace_id}/export",
        params={"format": "json"},
    )
    assert exported.status_code == 200
    assert "Evidence: graph reports help. Assumption: export is safe." not in str(
        exported.json()
    )


def test_failed_capability_paths_emit_failed_events(monkeypatch) -> None:
    _enable_six_flags(monkeypatch)

    def raise_report(self, *, workspace_id: str) -> dict[str, object]:
        raise RuntimeError("report failed")

    monkeypatch.setattr(GraphReportService, "build_report", raise_report)
    client = _build_client()
    workspace_id = "ws_six_failed_events"

    query = client.post(
        "/api/v1/research/query/run",
        json={"workspace_id": workspace_id, "tool_name": "write_store", "arguments": {}},
    )
    assert query.status_code == 400

    report = client.get(f"/api/v1/research/graph/{workspace_id}/report")
    assert report.status_code == 500

    graph_export = client.get(
        f"/api/v1/research/graph/{workspace_id}/export",
        params={"format": "xml"},
    )
    assert graph_export.status_code == 400

    package = STORE.create_package(
        workspace_id=workspace_id,
        title="failed export package",
        summary="summary",
        included_route_ids=[],
        included_node_ids=[],
        included_validation_ids=[],
    )
    package_export = client.get(
        f"/api/v1/research/packages/{package['package_id']}/export",
        params={"workspace_id": workspace_id, "format": "xml"},
    )
    assert package_export.status_code == 400

    events = STORE.list_events(workspace_id=workspace_id)
    failed_by_event = {
        str(event["event_name"]): event
        for event in events
        if str(event["status"]) == "failed"
    }
    for event_name in {
        "research_query_completed",
        "graph_report_completed",
        "graph_export_completed",
        "package_export_completed",
    }:
        assert event_name in failed_by_event
        assert failed_by_event[event_name]["error"]["error_code"]


def test_package_export_contract_requires_workspace_and_emits_failed_events(
    monkeypatch,
) -> None:
    _enable_six_flags(monkeypatch)
    client = _build_client()
    workspace_id = "ws_six_pkg_export"

    bootstrap = client.post(
        "/api/v1/research/sources/bootstrap",
        json={
            "workspace_id": workspace_id,
            "run_extract": False,
            "materials": [
                {
                    "source_type": "paper",
                    "title": "pkg seed",
                    "content": "Evidence: package export must be safe.",
                    "candidates": [
                        {
                            "candidate_type": "evidence",
                            "text": "Evidence: package export must be safe.",
                        }
                    ],
                }
            ],
        },
    )
    assert bootstrap.status_code == 200
    candidate_ids = bootstrap.json()["items"][0]["candidate_ids"]
    assert candidate_ids
    assert (
        client.post(
            "/api/v1/research/candidates/confirm",
            json={"workspace_id": workspace_id, "candidate_ids": candidate_ids},
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/research/graph/{workspace_id}/build").status_code == 200
    )
    graph = client.get(f"/api/v1/research/graph/{workspace_id}")
    node_ids = [item["node_id"] for item in graph.json()["nodes"]]
    package = client.post(
        "/api/v1/research/packages",
        json={
            "workspace_id": workspace_id,
            "title": "pkg",
            "summary": "pkg",
            "included_route_ids": [],
            "included_node_ids": node_ids[:1],
            "included_validation_ids": [],
        },
    )
    assert package.status_code == 200
    package_id = package.json()["package_id"]

    missing_workspace = client.get(
        f"/api/v1/research/packages/{package_id}/export",
        params={"format": "json"},
    )
    assert missing_workspace.status_code == 400

    mismatch = client.get(
        f"/api/v1/research/packages/{package_id}/export",
        params={"workspace_id": "ws_other", "format": "json"},
    )
    assert mismatch.status_code == 409

    invalid_format = client.get(
        f"/api/v1/research/packages/{package_id}/export",
        params={"workspace_id": workspace_id, "format": "xml"},
    )
    assert invalid_format.status_code == 400

    exported = client.get(
        f"/api/v1/research/packages/{package_id}/export",
        params={"workspace_id": workspace_id, "format": "json"},
    )
    assert exported.status_code == 200
    payload = exported.json()["payload"]
    assert "private_dependency_node_ids" not in str(payload)
    assert "replacement_map" not in str(payload)

    latest_export_error = STORE.find_latest_event(
        workspace_id=workspace_id,
        event_name="package_export_completed",
        ref_key="package_id",
        ref_value=package_id,
    )
    assert latest_export_error is not None
    assert latest_export_error["status"] == "completed"


def test_failure_events_and_local_first_provider_switch_keep_scores_stable(
    monkeypatch,
) -> None:
    _enable_six_flags(monkeypatch)
    client = _build_client()
    workspace_id = "ws_six_obs_det"

    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": workspace_id,
            "source_type": "paper",
            "title": "det seed",
            "content": "Claim: stability. Assumption: infra healthy. Failure: queue timeout.",
        },
    )
    assert imported.status_code == 200
    source_id = imported.json()["source_id"]

    extract = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": workspace_id, "async_mode": True},
        headers={
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert extract.status_code == 202
    assert wait_for_job_terminal(client, job_id=str(extract.json()["job_id"]))["status"] == "succeeded"
    candidates = client.get(
        "/api/v1/research/candidates",
        params={"workspace_id": workspace_id, "source_id": source_id},
    )
    candidate_ids = [item["candidate_id"] for item in candidates.json()["items"]]
    assert candidate_ids
    confirmed_count = 0
    for candidate_id in candidate_ids:
        confirmed = client.post(
            "/api/v1/research/candidates/confirm",
            json={"workspace_id": workspace_id, "candidate_ids": [candidate_id]},
        )
        if confirmed.status_code == 200:
            confirmed_count += 1
        else:
            assert confirmed.status_code == 409
    assert confirmed_count > 0
    assert (
        client.post(f"/api/v1/research/graph/{workspace_id}/build").status_code == 200
    )
    recompute = client.post(
        "/api/v1/research/routes/recompute",
        json={"workspace_id": workspace_id, "reason": "det baseline", "async_mode": True},
        headers={
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert recompute.status_code == 202
    route_job = wait_for_job_terminal(client, job_id=str(recompute.json()["job_id"]))
    route_id = str(route_job["result_ref"]["resource_id"])

    score_a = client.post(
        f"/api/v1/research/routes/{route_id}/score",
        json={"workspace_id": workspace_id},
    )
    route_a = client.get(
        f"/api/v1/research/routes/{route_id}",
        params={"workspace_id": workspace_id},
    )
    assert score_a.status_code == 200 and route_a.status_code == 200

    monkeypatch.setenv("RESEARCH_FEATURE_LOCAL_FIRST_ENABLED", "1")
    monkeypatch.setenv("RESEARCH_LOCAL_LLM_BACKEND", "ollama")
    monkeypatch.setenv("RESEARCH_LOCAL_LLM_MODEL", "qwen2")
    score_b = client.post(
        f"/api/v1/research/routes/{route_id}/score",
        json={"workspace_id": workspace_id},
    )
    route_b = client.get(
        f"/api/v1/research/routes/{route_id}",
        params={"workspace_id": workspace_id},
    )
    assert score_b.status_code == 200 and route_b.status_code == 200
    assert score_a.json()["support_score"] == score_b.json()["support_score"]
    assert score_a.json()["risk_score"] == score_b.json()["risk_score"]
    assert score_a.json()["progressability_score"] == score_b.json()["progressability_score"]
    assert route_a.json()["status"] == route_b.json()["status"]

    failed_query = client.post(
        "/api/v1/research/query/run",
        json={
            "workspace_id": workspace_id,
            "tool_name": "write_store",
            "arguments": {},
        },
    )
    assert failed_query.status_code == 400
    query_event = STORE.find_latest_event(
        workspace_id=workspace_id,
        event_name="research_query_completed",
        ref_key="tool_name",
        ref_value="write_store",
    )
    assert query_event is not None
    assert query_event["status"] == "failed"

    failed_export = client.get(
        f"/api/v1/research/graph/{workspace_id}/export",
        params={"format": "xml"},
    )
    assert failed_export.status_code == 400
    export_event = STORE.find_latest_event(
        workspace_id=workspace_id, event_name="graph_export_completed"
    )
    assert export_event is not None
    assert export_event["status"] == "failed"
