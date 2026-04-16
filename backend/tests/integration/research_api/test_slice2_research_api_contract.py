from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.middleware.global_exception_handler import global_exception_handler
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
from research_layer.testing.job_helpers import (
    TERMINAL_JOB_STATUSES,
    wait_for_job_terminal,
)


def _build_test_client() -> TestClient:
    STORE.reset_all()
    app = FastAPI()
    app.add_exception_handler(HTTPException, global_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)

    controllers = [
        ResearchSourceController(),
        ResearchRouteController(),
        ResearchGraphController(),
        ResearchFailureController(),
        ResearchHypothesisController(),
        ResearchPackageController(),
        ResearchJobController(),
        ResearchRetrievalController(),
    ]
    for controller in controllers:
        controller.register_to_app(app)

    @app.get("/api/v1/research/_test/unhandled")
    async def _raise_unhandled() -> dict[str, object]:
        raise RuntimeError("test boom")

    return TestClient(app, raise_server_exceptions=False)


def _assert_research_error_envelope(
    payload: dict[str, object], *, error_code: str | None = None
) -> None:
    assert isinstance(payload.get("error_code"), str)
    if error_code is not None:
        assert payload["error_code"] == error_code
    assert payload.get("message")
    assert isinstance(payload.get("details"), dict)
    assert isinstance(payload.get("trace_id"), str) and payload["trace_id"]
    assert isinstance(payload.get("request_id"), str) and payload["request_id"]
    assert payload.get("provider") is None
    assert payload.get("degraded") is False


def test_research_openapi_contains_primary_paths() -> None:
    client = _build_test_client()

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200

    paths = openapi.json()["paths"]
    assert "/api/v1/research/sources/import" in paths
    assert "/api/v1/research/sources" in paths
    assert "/api/v1/research/jobs/{job_id}" in paths
    assert "/api/v1/research/hypotheses" in paths
    assert "/api/v1/research/hypotheses/{hypothesis_id}/defer" in paths


def test_invalid_workspace_request_returns_explicit_error_semantics() -> None:
    client = _build_test_client()

    response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "bad id",
            "source_type": "paper",
            "title": "t",
            "content": "c",
        },
    )

    assert response.status_code == 400
    _assert_research_error_envelope(
        response.json(), error_code="research.invalid_request"
    )


def test_invalid_workspace_query_returns_research_error_structure() -> None:
    client = _build_test_client()

    response = client.get(
        "/api/v1/research/candidates", params={"workspace_id": "bad id"}
    )
    assert response.status_code == 400
    _assert_research_error_envelope(
        response.json(), error_code="research.invalid_request"
    )

    missing_workspace_response = client.get("/api/v1/research/candidates")
    assert missing_workspace_response.status_code == 400
    _assert_research_error_envelope(
        missing_workspace_response.json(), error_code="research.invalid_request"
    )

    source_invalid_workspace_response = client.get(
        "/api/v1/research/sources", params={"workspace_id": "bad id"}
    )
    assert source_invalid_workspace_response.status_code == 400
    _assert_research_error_envelope(
        source_invalid_workspace_response.json(), error_code="research.invalid_request"
    )

    source_missing_workspace_response = client.get("/api/v1/research/sources")
    assert source_missing_workspace_response.status_code == 400
    _assert_research_error_envelope(
        source_missing_workspace_response.json(), error_code="research.invalid_request"
    )

    hypothesis_invalid_workspace_response = client.get(
        "/api/v1/research/hypotheses", params={"workspace_id": "bad id"}
    )
    assert hypothesis_invalid_workspace_response.status_code == 400
    _assert_research_error_envelope(
        hypothesis_invalid_workspace_response.json(), error_code="research.invalid_request"
    )

    hypothesis_missing_workspace_response = client.get("/api/v1/research/hypotheses")
    assert hypothesis_missing_workspace_response.status_code == 400
    _assert_research_error_envelope(
        hypothesis_missing_workspace_response.json(), error_code="research.invalid_request"
    )


def test_get_route_enforces_workspace_ownership_contract() -> None:
    client = _build_test_client()

    created = STORE.create_route(
        workspace_id="ws_route_owner_01",
        title="r1",
        summary="s",
        status="candidate",
        support_score=0.1,
        risk_score=0.2,
        progressability_score=0.3,
        conclusion="c",
        key_supports=["k"],
        assumptions=["a"],
        risks=["r"],
        next_validation_action="n",
    )
    route_id = str(created["route_id"])

    ok = client.get(
        f"/api/v1/research/routes/{route_id}",
        params={"workspace_id": "ws_route_owner_01"},
    )
    assert ok.status_code == 200
    assert ok.json()["route_id"] == route_id

    mismatch = client.get(
        f"/api/v1/research/routes/{route_id}",
        params={"workspace_id": "ws_other_01"},
    )
    assert mismatch.status_code == 409
    _assert_research_error_envelope(mismatch.json(), error_code="research.conflict")

    missing = client.get(f"/api/v1/research/routes/{route_id}")
    assert missing.status_code == 400
    _assert_research_error_envelope(missing.json(), error_code="research.invalid_request")

    invalid = client.get(
        f"/api/v1/research/routes/{route_id}",
        params={"workspace_id": "bad id"},
    )
    assert invalid.status_code == 400
    _assert_research_error_envelope(invalid.json(), error_code="research.invalid_request")


def test_async_job_contract_supports_terminal_state_and_result_ref() -> None:
    client = _build_test_client()

    source_response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_alpha-01",
            "source_type": "paper",
            "title": "Research A",
            "content": "Evidence one. Assumption two.",
        },
    )
    assert source_response.status_code == 200
    source_id = source_response.json()["source_id"]

    start_response = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": "ws_alpha-01", "async_mode": True},
        headers={
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert start_response.status_code == 202
    job_id = start_response.json()["job_id"]

    job_response = client.get(f"/api/v1/research/jobs/{job_id}")
    assert job_response.status_code == 200
    job_payload = job_response.json()
    assert job_payload["status"] in {
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    }
    if job_payload["status"] not in TERMINAL_JOB_STATUSES or job_payload.get("result_ref") is None:
        job_payload = wait_for_job_terminal(client, job_id=str(job_id))

    assert job_payload.get("result_ref") is not None
    assert job_payload["result_ref"]["resource_type"] in {"source", "candidate_batch"}
    if job_payload["result_ref"]["resource_type"] == "source":
        assert job_payload["result_ref"]["resource_id"] == source_id
        source_get_response = client.get(
            f"/api/v1/research/sources/{job_payload['result_ref']['resource_id']}"
        )
        assert source_get_response.status_code == 200
    else:
        batch_id = job_payload["result_ref"]["resource_id"]
        result_response = client.get(
            f"/api/v1/research/sources/{source_id}/extraction-results/{batch_id}",
            params={"workspace_id": "ws_alpha-01"},
        )
        assert result_response.status_code == 200


def test_failure_semantics_http_error_uses_research_target_envelope() -> None:
    client = _build_test_client()

    response = client.get(
        "/api/v1/research/candidates", params={"workspace_id": "bad id"}
    )
    assert response.status_code == 400
    _assert_research_error_envelope(
        response.json(), error_code="research.invalid_request"
    )


def test_failure_semantics_unhandled_research_error_is_explicit() -> None:
    client = _build_test_client()

    response = client.get("/api/v1/research/_test/unhandled")
    assert response.status_code == 500
    payload = response.json()
    _assert_research_error_envelope(payload)
    assert payload["error_code"].startswith("research.")
    assert payload["message"] == "Internal server error"


def test_malformed_json_in_route_controller_returns_invalid_request() -> None:
    client = _build_test_client()
    response = client.post(
        "/api/v1/research/routes/generate",
        content='{"workspace_id":',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    _assert_research_error_envelope(
        response.json(), error_code="research.invalid_request"
    )


def test_malformed_json_in_failure_controller_returns_invalid_request() -> None:
    client = _build_test_client()
    response = client.post(
        "/api/v1/research/failures",
        content='{"workspace_id":',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    _assert_research_error_envelope(
        response.json(), error_code="research.invalid_request"
    )


def test_malformed_json_in_hypothesis_controller_returns_invalid_request() -> None:
    client = _build_test_client()
    response = client.post(
        "/api/v1/research/hypotheses/generate",
        content='{"workspace_id":',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    _assert_research_error_envelope(
        response.json(), error_code="research.invalid_request"
    )


def test_malformed_json_in_retrieval_controller_returns_invalid_request() -> None:
    client = _build_test_client()
    response = client.post(
        "/api/v1/research/retrieval/views/evidence",
        content='{"workspace_id":',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    _assert_research_error_envelope(
        response.json(), error_code="research.invalid_request"
    )
