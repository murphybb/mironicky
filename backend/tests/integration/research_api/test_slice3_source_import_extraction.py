from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers.research_failure_controller import (
    ResearchFailureController,
)
from research_layer.api.controllers.research_graph_controller import ResearchGraphController
from research_layer.api.controllers.research_hypothesis_controller import (
    ResearchHypothesisController,
)
from research_layer.api.controllers.research_job_controller import ResearchJobController
from research_layer.api.controllers.research_package_controller import (
    ResearchPackageController,
)
from research_layer.api.controllers.research_route_controller import ResearchRouteController
from research_layer.api.controllers.research_source_controller import (
    ResearchSourceController,
)
from research_layer.api.schemas.source import CANDIDATE_TYPE_VALUES
from research_layer.services.source_import_service import SourceImportError, SourceImportService
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


def test_slice3_dev_console_entrypoint_exists() -> None:
    client = _build_test_client()
    response = client.get("/api/v1/research/dev-console")
    assert response.status_code == 200
    assert "Research Dev Console" in response.text
    assert "/api/v1/research/sources/import" in response.text


def test_empty_and_invalid_import_input_returns_explicit_error() -> None:
    client = _build_test_client()

    empty_response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_slice3",
            "source_type": "paper",
            "title": "empty",
            "content": "",
        },
    )
    assert empty_response.status_code == 400
    assert empty_response.json()["detail"]["error_code"] == "research.invalid_request"

    invalid_type_response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_slice3",
            "source_type": "unknown_type",
            "title": "invalid",
            "content": "x",
        },
    )
    assert invalid_type_response.status_code == 400
    assert invalid_type_response.json()["detail"]["error_code"] == "research.invalid_request"


def test_url_source_import_auto_detects_mode_and_enriches_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        SourceImportService,
        "_fetch_url_html",
        lambda _self, _url: (
            "<html><head><title>URL Auto Detect Title</title>"
            '<link rel="canonical" href="https://example.org/canonical-article" /></head>'
            "<body><article>Auto extracted article content for source import.</article></body></html>"
        ),
    )
    client = _build_test_client()
    response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_url_auto",
            "source_type": "paper",
            "source_input_mode": "auto",
            "source_input": "https://example.org/article",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "URL Auto Detect Title"
    assert payload["metadata"]["source_input_mode"] == "url"
    assert payload["metadata"]["url"] == "https://example.org/canonical-article"
    assert "Auto extracted article content" in payload["content"]


def test_url_source_import_remote_fetch_failure_is_explicit(monkeypatch) -> None:
    def _raise_remote_fetch(_self, _url: str) -> str:
        raise SourceImportError(
            error_code="research.source_import_remote_fetch_failed",
            message="failed to fetch URL content",
            details={"source_url": _url},
            status_code=502,
        )

    monkeypatch.setattr(SourceImportService, "_fetch_url_html", _raise_remote_fetch)
    client = _build_test_client()
    response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_url_fail",
            "source_type": "paper",
            "source_input_mode": "url",
            "source_url": "https://example.org/unreachable",
        },
    )
    assert response.status_code == 502
    assert (
        response.json()["detail"]["error_code"]
        == "research.source_import_remote_fetch_failed"
    )


def test_local_file_import_unsupported_format_is_explicit() -> None:
    client = _build_test_client()
    response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_local_bad",
            "source_type": "paper",
            "source_input_mode": "local_file",
            "local_file": {
                "file_name": "unsupported.txt",
                "file_content_base64": "dGVzdA==",
            },
        },
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"]["error_code"]
        == "research.source_import_unsupported_format"
    )


def test_import_extract_and_candidate_traceability_for_required_source_types() -> None:
    client = _build_test_client()
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "demo"
        / "research_dev"
        / "fixtures"
        / "slice3_sources.json"
    )
    fixture_payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    expected_type_map = {
        "paper": {"evidence", "assumption", "validation"},
        "note": {"assumption", "conflict", "validation"},
        "failure_record": {"failure", "evidence"},
    }

    for idx, source_item in enumerate(fixture_payload["sources"]):
        workspace_id = f"ws_slice3_{idx}"
        import_response = client.post(
            "/api/v1/research/sources/import",
            json={
                "workspace_id": workspace_id,
                "source_type": source_item["source_type"],
                "title": source_item["title"],
                "content": source_item["content"],
            },
        )
        assert import_response.status_code == 200
        source_id = import_response.json()["source_id"]

        start_response = client.post(
            f"/api/v1/research/sources/{source_id}/extract",
            json={"workspace_id": workspace_id, "async_mode": True},
            headers={
                "x-research-llm-failure-mode": "invalid_json",
                "x-research-llm-allow-fallback": "1",
            },
        )
        assert start_response.status_code == 202
        job_id = start_response.json()["job_id"]

        job_payload = wait_for_job_terminal(client, job_id=str(job_id))
        assert job_payload["status"] == "succeeded"
        assert job_payload["result_ref"]["resource_type"] == "candidate_batch"

        batch_id = job_payload["result_ref"]["resource_id"]
        batch_response = client.get(
            f"/api/v1/research/sources/{source_id}/extraction-results/{batch_id}",
            params={"workspace_id": workspace_id},
        )
        assert batch_response.status_code == 200
        batch_payload = batch_response.json()
        assert batch_payload["job_id"] == job_id
        assert batch_payload["source_id"] == source_id
        assert batch_payload["candidate_batch_id"] == batch_id
        assert batch_payload["status"] == "succeeded"
        assert batch_payload["provider_backend"]
        assert batch_payload["provider_model"]
        assert batch_payload["llm_request_id"]
        assert batch_payload["llm_response_id"]
        usage = batch_payload.get("usage") or {}
        assert "prompt_tokens" in usage
        assert "completion_tokens" in usage
        assert "total_tokens" in usage
        assert isinstance(batch_payload["degraded"], bool)
        assert isinstance(batch_payload["fallback_used"], bool)

        candidate_response = client.get(
            "/api/v1/research/candidates",
            params={"workspace_id": workspace_id, "source_id": source_id},
        )
        assert candidate_response.status_code == 200
        items = candidate_response.json()["items"]
        assert items
        observed_types = {item["candidate_type"] for item in items}
        assert observed_types.issubset(
            CANDIDATE_TYPE_VALUES
        ), "unexpected candidate_type emitted"
        assert (
            observed_types & expected_type_map[source_item["source_type"]]
        ), "no source-type-aligned candidate_type was produced"
        for item in items:
            assert item["source_id"] == source_id
            assert item["workspace_id"] == workspace_id
            assert item["candidate_batch_id"] == batch_id
            assert item["source_span"]["end"] > item["source_span"]["start"]
            assert item["provider_backend"]
            assert item["provider_model"]
            assert item["request_id"]
            assert item["llm_response_id"]
            candidate_usage = item.get("usage") or {}
            assert "prompt_tokens" in candidate_usage
            assert "completion_tokens" in candidate_usage
            assert "total_tokens" in candidate_usage
            assert isinstance(item["degraded"], bool)
            assert isinstance(item["fallback_used"], bool)


def test_parse_failure_sets_job_failed_and_keeps_error_visible() -> None:
    client = _build_test_client()
    import_response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_parse_fail",
            "source_type": "note",
            "title": "parse fail",
            "content": "[[PARSE_FAIL]]",
        },
    )
    source_id = import_response.json()["source_id"]

    start_response = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": "ws_parse_fail", "async_mode": True},
    )
    assert start_response.status_code == 202
    job_id = start_response.json()["job_id"]

    job_payload = wait_for_job_terminal(client, job_id=str(job_id))
    assert job_payload["status"] == "failed"
    assert (
        job_payload["error"]["error_code"]
        == "research.source_import_parse_failed"
    )


def test_extract_failure_is_not_swallowed() -> None:
    client = _build_test_client()
    import_response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_extract_fail",
            "source_type": "paper",
            "title": "extract fail",
            "content": "Claim: ok. This path verifies explicit provider failure.",
        },
    )
    source_id = import_response.json()["source_id"]

    start_response = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": "ws_extract_fail", "async_mode": True},
        headers={"x-research-llm-failure-mode": "invalid_json"},
    )
    assert start_response.status_code == 202
    job_id = start_response.json()["job_id"]

    job_payload = wait_for_job_terminal(client, job_id=str(job_id))
    assert job_payload["status"] == "failed"
    assert job_payload["error"]["error_code"] == "research.llm_invalid_output"


def test_workspace_id_conflict_is_enforced_for_extract() -> None:
    client = _build_test_client()
    import_response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_owner",
            "source_type": "paper",
            "title": "owner",
            "content": "Claim: owner only.",
        },
    )
    source_id = import_response.json()["source_id"]

    response = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": "ws_intruder", "async_mode": True},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "research.conflict"


def test_extract_rejects_async_mode_false() -> None:
    client = _build_test_client()
    import_response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_async_false_extract",
            "source_type": "paper",
            "title": "async false extract",
            "content": "Claim: enforce async contract.",
        },
    )
    assert import_response.status_code == 200
    source_id = import_response.json()["source_id"]

    response = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": "ws_async_false_extract", "async_mode": False},
        headers={"x-request-id": "req_slice3_async_false_extract"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error_code"] == "research.invalid_request"
    assert "async_mode must be true" in detail["message"]


def test_source_import_started_event_binds_to_created_source() -> None:
    client = _build_test_client()
    response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_event_bind",
            "source_type": "paper",
            "title": "event source",
            "content": "Claim: event binding check.",
        },
    )
    assert response.status_code == 200
    source_id = response.json()["source_id"]

    with sqlite3.connect(STORE.db_path) as conn:
        row = conn.execute(
            """
            SELECT source_id, candidate_batch_id, request_id
            FROM research_events
            WHERE event_name = 'source_import_started'
            ORDER BY rowid DESC
            LIMIT 1
            """
        ).fetchone()

    assert row is not None
    assert row[0] == source_id
    assert row[1] is None
    assert row[2] is not None


def test_sources_list_returns_real_workspace_scoped_materials() -> None:
    client = _build_test_client()
    ws_primary = "ws_sources_primary"
    ws_other = "ws_sources_other"

    imported_primary: list[str] = []
    for idx in range(2):
        response = client.post(
            "/api/v1/research/sources/import",
            json={
                "workspace_id": ws_primary,
                "source_type": "paper",
                "title": f"primary-{idx}",
                "content": f"primary content {idx}",
            },
        )
        assert response.status_code == 200
        imported_primary.append(response.json()["source_id"])

    other_response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": ws_other,
            "source_type": "note",
            "title": "other",
            "content": "other content",
        },
    )
    assert other_response.status_code == 200

    list_response = client.get("/api/v1/research/sources", params={"workspace_id": ws_primary})
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["total"] == 2
    source_ids = [item["source_id"] for item in payload["items"]]
    assert set(source_ids) == set(imported_primary)
    assert all(item["workspace_id"] == ws_primary for item in payload["items"])

    other_list_response = client.get(
        "/api/v1/research/sources", params={"workspace_id": ws_other}
    )
    assert other_list_response.status_code == 200
    other_payload = other_list_response.json()
    assert other_payload["total"] == 1
    assert other_payload["items"][0]["workspace_id"] == ws_other


def _assert_invalid_request_response(response, *, reason_fragment: str) -> None:
    assert response.status_code == 400
    payload = response.json()["detail"]
    assert payload["error_code"] == "research.invalid_request"
    assert payload["message"] == "request validation failed"
    assert "errors" in payload["details"]
    serialized = json.dumps(payload["details"]["errors"], ensure_ascii=False)
    assert reason_fragment in serialized


def test_slice3_write_endpoints_convert_invalid_request_bodies_into_explicit_400() -> None:
    client = _build_test_client()
    workspace_id = "ws_slice3_invalid_bodies"
    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": workspace_id,
            "source_type": "paper",
            "title": "seed",
            "content": "Claim: seed for invalid body cases.",
        },
    )
    assert imported.status_code == 200
    source_id = imported.json()["source_id"]

    endpoints = [
        ("import", "POST", "/api/v1/research/sources/import"),
        ("extract", "POST", f"/api/v1/research/sources/{source_id}/extract"),
    ]

    valid_object_payloads = {
        "import": {
            "workspace_id": workspace_id,
            "source_type": "paper",
            "title": "seed",
            "content": "Claim: valid object baseline.",
        },
        "extract": {"workspace_id": workspace_id, "async_mode": True},
    }

    non_object_payloads = [
        ("[]", "JSON object"),
        ('"abc"', "JSON object"),
        ("123", "JSON object"),
        ("true", "JSON object"),
    ]

    for name, method, url in endpoints:
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

        for raw_payload, expected_fragment in non_object_payloads:
            non_object_response = client.request(
                method,
                url,
                data=raw_payload,
                headers={"Content-Type": "application/json"},
            )
            _assert_invalid_request_response(
                non_object_response, reason_fragment=expected_fragment
            )

        missing_workspace_response = client.request(
            method,
            url,
            json={
                key: value
                for key, value in valid_object_payloads[name].items()
                if key != "workspace_id"
            },
        )
        _assert_invalid_request_response(
            missing_workspace_response, reason_fragment="workspace_id"
        )
