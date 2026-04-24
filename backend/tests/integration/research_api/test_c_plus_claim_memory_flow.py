from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers.research_job_controller import ResearchJobController
from research_layer.api.controllers.research_source_controller import ResearchSourceController
from research_layer.services.evermemos_bridge_service import EverMemOSRecallService
from research_layer.services.source_memory_recall_service import SourceMemoryRecallService
from research_layer.testing.job_helpers import wait_for_job_terminal
from research_layer.workers.extraction_worker import ExtractionWorker


def _build_test_client() -> TestClient:
    STORE.reset_all()
    app = FastAPI()
    for controller in (ResearchSourceController(), ResearchJobController()):
        controller.register_to_app(app)
    return TestClient(app)


def test_task2_source_import_response_and_store_include_memory_recall(monkeypatch) -> None:
    def _fake_recall(self, **kwargs):
        return {
            "status": "completed",
            "reason": "logical_not_supported_by_evermemos",
            "requested_method": kwargs["requested_method"],
            "applied_method": "hybrid",
            "query_text": kwargs["query_text"],
            "total": 1,
            "items": [
                {
                    "memory_type": "episodic_memory",
                    "memory_id": "mem_import_1",
                    "score": 0.88,
                    "title": "historical claim",
                    "snippet": "historical context",
                    "linked_claim_refs": [{"claim_id": "claim_old"}],
                    "trace_refs": {},
                }
            ],
            "trace_refs": {"request_id": kwargs.get("request_id")},
        }

    monkeypatch.setattr(EverMemOSRecallService, "recall", _fake_recall)
    client = _build_test_client()

    response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_task2_import",
            "source_type": "paper",
            "title": "Task2 import source",
            "content": "Claim: brand attitude changes when prior context is recalled.",
        },
        headers={"x-request-id": "req_task2_import"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["memory_recall"]["status"] == "completed"
    assert payload["memory_recall"]["query_text"] == "Claim: brand attitude changes when prior context is recalled."
    assert payload["memory_recall"]["items"][0]["memory_id"] == "mem_import_1"
    stored = STORE.list_source_memory_recall_results(
        workspace_id="ws_task2_import",
        source_id=payload["source_id"],
    )
    assert len(stored) == 1
    assert stored[0]["request_id"] == "req_task2_import"
    assert stored[0]["query_text"] == "Claim: brand attitude changes when prior context is recalled."


def test_source_import_succeeds_when_memory_recall_side_effect_raises(
    monkeypatch,
) -> None:
    def _raise_recall(self, **_kwargs):
        raise RuntimeError("recall store unavailable")

    monkeypatch.setattr(SourceMemoryRecallService, "recall_for_source", _raise_recall)
    client = _build_test_client()

    response = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_task2_import_recall_failure",
            "source_type": "paper",
            "title": "Task2 import recall failure source",
            "content": "Claim: source import must not depend on recall side effects.",
        },
        headers={"x-request-id": "req_task2_import_recall_failure"},
    )

    assert response.status_code == 200
    source_id = response.json()["source_id"]
    detail = client.get(f"/api/v1/research/sources/{source_id}")
    assert detail.status_code == 200
    assert detail.json()["source_id"] == source_id


def test_task2_source_extract_persists_explicit_memory_recall(monkeypatch) -> None:
    for name in ("MONGODB_HOST", "ES_HOSTS", "MILVUS_HOST"):
        monkeypatch.delenv(name, raising=False)

    async def _fake_extract_run(
        self,
        *,
        request_id,
        job_id,
        workspace_id,
        source_id,
        failure_mode=None,
        allow_fallback=False,
    ):
        self._store.start_job(job_id)
        batch = self._store.create_candidate_batch(
            workspace_id=workspace_id,
            source_id=source_id,
            job_id=job_id,
            request_id=request_id,
        )
        persisted = self._store.add_candidates_to_batch(
            candidate_batch_id=str(batch["candidate_batch_id"]),
            workspace_id=workspace_id,
            source_id=source_id,
            job_id=job_id,
            candidates=[
                {
                    "candidate_type": "evidence",
                    "text": "recall status must be explicit after extraction",
                    "source_span": {"start": 0, "end": 48},
                    "extractor_name": "test_fake_extractor",
                }
            ],
        )
        self._store.update_source_processing(
            source_id=source_id,
            status="extracted",
            last_extract_job_id=job_id,
        )
        self._store.finish_job_success(
            job_id=job_id,
            result_ref={
                "resource_type": "candidate_batch",
                "resource_id": str(batch["candidate_batch_id"]),
            },
        )
        return {
            "status": "succeeded",
            "candidate_batch_id": str(batch["candidate_batch_id"]),
            "candidate_count": len(persisted),
        }

    monkeypatch.setattr(ExtractionWorker, "run", _fake_extract_run)
    client = _build_test_client()
    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_task2_extract",
            "source_type": "paper",
            "title": "Task2 extract source",
            "content": "Claim: recall status must be explicit after extraction.",
        },
        headers={"x-request-id": "req_task2_extract_import"},
    )
    assert imported.status_code == 200
    source_id = imported.json()["source_id"]

    started = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": "ws_task2_extract", "async_mode": True},
        headers={
            "x-request-id": "req_task2_extract",
            "x-research-llm-failure-mode": "invalid_json",
            "x-research-llm-allow-fallback": "1",
        },
    )
    assert started.status_code == 202
    job = wait_for_job_terminal(client, job_id=started.json()["job_id"])
    assert job["status"] == "succeeded"

    stored = STORE.list_source_memory_recall_results(
        workspace_id="ws_task2_extract",
        source_id=source_id,
    )
    assert stored[0]["status"] == "skipped"
    assert str(stored[0]["reason"]).startswith("evermemos_recall_unconfigured")

    detail = client.get(f"/api/v1/research/sources/{source_id}")
    assert detail.status_code == 200
    assert detail.json()["memory_recall"]["status"] == "skipped"
    assert detail.json()["memory_recall"]["reason"].startswith(
        "evermemos_recall_unconfigured"
    )
    listed = client.get(
        "/api/v1/research/sources",
        params={"workspace_id": "ws_task2_extract"},
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["memory_recall"]["status"] == "skipped"
    assert listed.json()["items"][0]["memory_recall"]["reason"].startswith(
        "evermemos_recall_unconfigured"
    )


def test_source_extract_job_succeeds_when_memory_recall_side_effect_raises(
    monkeypatch,
) -> None:
    for name in ("MONGODB_HOST", "ES_HOSTS", "MILVUS_HOST"):
        monkeypatch.delenv(name, raising=False)

    async def _fake_extract_run(
        self,
        *,
        request_id,
        job_id,
        workspace_id,
        source_id,
        failure_mode=None,
        allow_fallback=False,
    ):
        self._store.start_job(job_id)
        batch = self._store.create_candidate_batch(
            workspace_id=workspace_id,
            source_id=source_id,
            job_id=job_id,
            request_id=request_id,
        )
        self._store.add_candidates_to_batch(
            candidate_batch_id=str(batch["candidate_batch_id"]),
            workspace_id=workspace_id,
            source_id=source_id,
            job_id=job_id,
            candidates=[
                {
                    "candidate_type": "evidence",
                    "text": "extract job must not depend on recall side effects",
                    "source_span": {"start": 0, "end": 55},
                    "extractor_name": "test_fake_extractor",
                }
            ],
        )
        self._store.update_source_processing(
            source_id=source_id,
            status="extracted",
            last_extract_job_id=job_id,
        )
        self._store.finish_job_success(
            job_id=job_id,
            result_ref={
                "resource_type": "candidate_batch",
                "resource_id": str(batch["candidate_batch_id"]),
            },
        )
        return {
            "status": "succeeded",
            "candidate_batch_id": str(batch["candidate_batch_id"]),
            "candidate_count": 1,
        }

    def _raise_recall(self, **_kwargs):
        raise RuntimeError("recall event unavailable")

    monkeypatch.setattr(ExtractionWorker, "run", _fake_extract_run)
    client = _build_test_client()
    imported = client.post(
        "/api/v1/research/sources/import",
        json={
            "workspace_id": "ws_task2_extract_recall_failure",
            "source_type": "paper",
            "title": "Task2 extract recall failure source",
            "content": "Claim: source extract must not depend on recall side effects.",
        },
        headers={"x-request-id": "req_task2_extract_recall_failure_import"},
    )
    assert imported.status_code == 200
    source_id = imported.json()["source_id"]
    monkeypatch.setattr(SourceMemoryRecallService, "recall_for_source", _raise_recall)

    started = client.post(
        f"/api/v1/research/sources/{source_id}/extract",
        json={"workspace_id": "ws_task2_extract_recall_failure", "async_mode": True},
        headers={"x-request-id": "req_task2_extract_recall_failure"},
    )
    assert started.status_code == 202
    job = wait_for_job_terminal(client, job_id=started.json()["job_id"])
    assert job["status"] == "succeeded"

    detail = client.get(f"/api/v1/research/sources/{source_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] != "extract_failed"
