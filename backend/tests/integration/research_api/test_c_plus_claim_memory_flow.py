from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers.research_conflict_controller import (
    ResearchConflictController,
)
from research_layer.api.controllers.research_cross_document_report_controller import (
    ResearchCrossDocumentReportController,
)
from research_layer.api.controllers.research_graphrag_controller import (
    ResearchGraphRAGController,
)
from research_layer.api.controllers.research_job_controller import ResearchJobController
from research_layer.api.controllers.research_source_controller import ResearchSourceController
from research_layer.services.candidate_confirmation_service import normalize_candidate_text
from research_layer.services.claim_conflict_service import ClaimConflictService
from research_layer.services.evermemos_bridge_service import EverMemOSRecallService
from research_layer.services.source_memory_recall_service import SourceMemoryRecallService
from research_layer.testing.job_helpers import wait_for_job_terminal
from research_layer.workers.extraction_worker import ExtractionWorker


def _build_test_client() -> TestClient:
    STORE.reset_all()
    app = FastAPI()
    for controller in (
        ResearchSourceController(),
        ResearchJobController(),
        ResearchConflictController(),
        ResearchGraphRAGController(),
        ResearchCrossDocumentReportController(),
    ):
        controller.register_to_app(app)
    return TestClient(app)


def _create_candidate(workspace_id: str, text: str) -> dict[str, object]:
    source = STORE.create_source(
        workspace_id=workspace_id,
        source_type="paper",
        title=text[:40],
        content=text,
        metadata={},
        import_request_id="req_task3_candidate",
    )
    batch = STORE.create_candidate_batch(
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id="job_task3_candidate",
        request_id="req_task3_candidate",
    )
    return STORE.add_candidates_to_batch(
        candidate_batch_id=str(batch["candidate_batch_id"]),
        workspace_id=workspace_id,
        source_id=str(source["source_id"]),
        job_id="job_task3_candidate",
        candidates=[
            {
                "candidate_type": "evidence",
                "text": text,
                "source_span": {"start": 0, "end": len(text)},
                "trace_refs": {"source_id": source["source_id"]},
                "extractor_name": "test_task3",
            }
        ],
    )[0]


def test_task5_graphrag_query_returns_answer_citations_and_memory_recall(
    monkeypatch,
) -> None:
    def _fake_recall(self, **kwargs):
        scoped_claim_ids = list(kwargs.get("scope_claim_ids") or [])
        return {
            "status": "completed",
            "reason": None,
            "requested_method": kwargs["requested_method"],
            "applied_method": "hybrid",
            "query_text": kwargs["query_text"],
            "total": 1 if scoped_claim_ids else 0,
            "items": [
                {
                    "memory_type": "event_log",
                    "memory_id": "mem_graphrag_1",
                    "score": 0.77,
                    "title": "prior timeout context",
                    "snippet": "shard imbalance was seen before",
                    "linked_claim_refs": [
                        {"claim_id": str(scoped_claim_ids[0])}
                    ],
                    "trace_refs": {},
                }
            ]
            if scoped_claim_ids
            else [],
            "trace_refs": {"request_id": kwargs.get("request_id")},
        }

    monkeypatch.setattr(EverMemOSRecallService, "recall", _fake_recall)
    client = _build_test_client()
    workspace_id = "ws_task5_graphrag"
    candidate = _create_candidate(
        workspace_id,
        "Shard imbalance increases timeout latency in retrieval.",
    )
    object_ref = STORE.create_confirmed_object_from_candidate(
        candidate=candidate,
        normalized_text=normalize_candidate_text(str(candidate["text"])),
        request_id="req_task5_confirm",
    )
    claim = STORE.create_claim_from_candidate(
        candidate=candidate,
        normalized_text=normalize_candidate_text(str(candidate["text"])),
    )
    STORE.create_graph_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type=str(object_ref["object_type"]),
        object_ref_id=str(object_ref["object_id"]),
        short_label="Timeout evidence",
        full_description="Evidence that shard imbalance increases timeout latency",
        claim_id=str(claim["claim_id"]),
        source_ref={"source_id": str(candidate["source_id"])},
    )

    response = client.post(
        "/api/v1/research/graphrag/query",
        json={
            "workspace_id": workspace_id,
            "question": "What increases timeout latency?",
            "limit": 8,
        },
        headers={"x-request-id": "req_task5_graphrag"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].startswith("Based on")
    assert payload["citations"]
    assert payload["citations"][0]["claim_id"] == claim["claim_id"]
    assert payload["citations"][0]["source_ref"]["source_id"] == candidate["source_id"]
    assert payload["memory_recall"]["items"][0]["memory_id"] == "mem_graphrag_1"
    assert payload["trace_refs"]["request_id"] == "req_task5_graphrag"


def test_task5_graphrag_query_rejects_blank_question() -> None:
    client = _build_test_client()

    response = client.post(
        "/api/v1/research/graphrag/query",
        json={
            "workspace_id": "ws_task5_blank_question",
            "question": "   ",
            "limit": 8,
        },
        headers={"x-request-id": "req_task5_blank_question"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "research.invalid_request"


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


def test_task3_conflict_api_lists_and_patches_review_state() -> None:
    client = _build_test_client()
    workspace_id = "ws_task3_api"
    first = _create_candidate(workspace_id, "Brand trust increases purchase intention.")
    old_claim = STORE.create_claim_from_candidate(
        candidate=first,
        normalized_text=str(first["text"]).lower(),
    )
    second = _create_candidate(
        workspace_id,
        "Brand trust does not increase purchase intention.",
    )
    new_claim = STORE.create_claim_from_candidate(
        candidate=second,
        normalized_text=str(second["text"]).lower(),
    )
    conflict = STORE.create_claim_conflict(
        workspace_id=workspace_id,
        new_claim_id=str(new_claim["claim_id"]),
        existing_claim_id=str(old_claim["claim_id"]),
        conflict_type="possible_contradiction",
        status="needs_review",
        evidence={"detector": "test", "new_text": new_claim["text"]},
        source_ref={"new_claim_id": new_claim["claim_id"]},
        created_request_id="req_task3_api",
    )

    listed = client.get(f"/api/v1/research/conflicts/{workspace_id}")

    assert listed.status_code == 200
    assert listed.json()["items"][0]["conflict_id"] == conflict["conflict_id"]
    assert listed.json()["items"][0]["status"] == "needs_review"

    patched = client.patch(
        f"/api/v1/research/conflicts/{conflict['conflict_id']}",
        json={
            "workspace_id": workspace_id,
            "status": "accepted",
            "decision_note": "reviewed",
        },
        headers={"x-request-id": "req_task3_patch"},
    )

    assert patched.status_code == 200
    payload = patched.json()
    assert payload["status"] == "accepted"
    assert payload["decision_note"] == "reviewed"
    assert payload["resolved_request_id"] == "req_task3_patch"


def test_task3_candidate_confirmation_creates_claim_conflict() -> None:
    client = _build_test_client()
    workspace_id = "ws_task3_confirm"
    old_candidate = _create_candidate(
        workspace_id,
        "Brand trust increases purchase intention.",
    )
    new_candidate = _create_candidate(
        workspace_id,
        "Brand trust does not increase purchase intention.",
    )

    first = client.post(
        "/api/v1/research/candidates/confirm",
        json={
            "workspace_id": workspace_id,
            "candidate_ids": [old_candidate["candidate_id"]],
        },
        headers={"x-request-id": "req_task3_first_confirm"},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/v1/research/candidates/confirm",
        json={
            "workspace_id": workspace_id,
            "candidate_ids": [new_candidate["candidate_id"]],
        },
        headers={"x-request-id": "req_task3_second_confirm"},
    )
    assert second.status_code == 200

    listed = client.get(f"/api/v1/research/conflicts/{workspace_id}")

    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "needs_review"
    assert items[0]["conflict_type"] == "possible_contradiction"
    assert items[0]["created_request_id"] == "req_task3_second_confirm"


def test_task6_cross_document_report_endpoint_returns_summary_and_sections() -> None:
    client = _build_test_client()
    workspace_id = "ws_task6_report"
    old_candidate = _create_candidate(workspace_id, "Task6 evidence improves recall.")
    old_claim = STORE.create_claim_from_candidate(
        candidate=old_candidate,
        normalized_text=str(old_candidate["text"]).lower(),
    )
    new_candidate = _create_candidate(
        workspace_id,
        "Task6 evidence does not improve recall.",
    )
    new_claim = STORE.create_claim_from_candidate(
        candidate=new_candidate,
        normalized_text=str(new_candidate["text"]).lower(),
    )
    conflict = STORE.create_claim_conflict(
        workspace_id=workspace_id,
        new_claim_id=str(new_claim["claim_id"]),
        existing_claim_id=str(old_claim["claim_id"]),
        conflict_type="possible_contradiction",
        status="needs_review",
        evidence={"detector": "test"},
        source_ref={"new_claim_id": new_claim["claim_id"]},
        created_request_id="req_task6_conflict",
    )
    STORE.create_source_memory_recall_result(
        workspace_id=workspace_id,
        source_id=str(new_claim["source_id"]),
        status="completed",
        reason=None,
        requested_method="logical",
        applied_method="hybrid",
        query_text=str(new_claim["text"]),
        total=1,
        items=[
            {
                "memory_type": "episodic_memory",
                "memory_id": "mem_task6_1",
                "score": 0.8,
                "title": "Task6 prior result",
                "snippet": "Prior result is relevant to the new claim.",
                "linked_claim_refs": [{"claim_id": old_claim["claim_id"]}],
                "trace_refs": {},
            }
        ],
        trace_refs={"request_id": "req_task6_recall"},
        error=None,
        request_id="req_task6_recall",
    )

    response = client.get(
        f"/api/v1/research/reports/{workspace_id}/cross-document",
        headers={"x-request-id": "req_task6_report"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_id"] == workspace_id
    assert payload["summary"]["claim_count"] == 2
    assert payload["summary"]["conflict_count"] == 1
    assert payload["summary"]["source_recall_count"] == 1
    assert payload["sections"]["claims"][0]["claim_id"] == old_claim["claim_id"]
    assert payload["sections"]["conflicts"][0]["conflict_id"] == conflict["conflict_id"]
    assert payload["sections"]["historical_recall"][0]["items"][0]["memory_id"] == "mem_task6_1"
    assert payload["sections"]["unresolved_gaps"][0]["gap_type"] == "claim_conflict"
    assert payload["trace_refs"]["request_id"] == "req_task6_report"


def test_task3_candidate_confirmation_checks_claims_after_first_50() -> None:
    client = _build_test_client()
    workspace_id = "ws_task3_confirm_after_50"
    for index in range(55):
        filler = _create_candidate(workspace_id, f"Unrelated neutral claim number {index}.")
        STORE.create_claim_from_candidate(
            candidate=filler,
            normalized_text=str(filler["text"]).lower(),
        )
    old_candidate = _create_candidate(
        workspace_id,
        "Brand trust increases purchase intention.",
    )
    old_claim = STORE.create_claim_from_candidate(
        candidate=old_candidate,
        normalized_text=str(old_candidate["text"]).lower(),
    )
    new_candidate = _create_candidate(
        workspace_id,
        "Brand trust does not increase purchase intention.",
    )

    second = client.post(
        "/api/v1/research/candidates/confirm",
        json={
            "workspace_id": workspace_id,
            "candidate_ids": [new_candidate["candidate_id"]],
        },
        headers={"x-request-id": "req_task3_new_after_50_confirm"},
    )
    assert second.status_code == 200

    listed = client.get(f"/api/v1/research/conflicts/{workspace_id}")

    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["existing_claim_id"] == old_claim["claim_id"]
    assert items[0]["created_request_id"] == "req_task3_new_after_50_confirm"


def test_task3_candidate_confirmation_succeeds_when_conflict_detection_fails(
    monkeypatch,
) -> None:
    def _raise_detection(self, **_kwargs):
        raise RuntimeError("detector unavailable")

    monkeypatch.setattr(ClaimConflictService, "detect_for_claim", _raise_detection)
    client = _build_test_client()
    workspace_id = "ws_task3_confirm_detector_failure"
    candidate = _create_candidate(
        workspace_id,
        "Candidate confirmation should survive detector failure.",
    )

    response = client.post(
        "/api/v1/research/candidates/confirm",
        json={
            "workspace_id": workspace_id,
            "candidate_ids": [candidate["candidate_id"]],
        },
        headers={"x-request-id": "req_task3_detector_failure"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "confirmed"
    assert payload["updated_ids"] == [candidate["candidate_id"]]
    events = STORE.list_events(
        workspace_id=workspace_id,
        request_id="req_task3_detector_failure",
    )
    failed_events = [
        event
        for event in events
        if event["event_name"] == "claim_conflict_detection_completed"
        and event["status"] == "failed"
    ]
    assert len(failed_events) == 1
    assert failed_events[0]["refs"]["reason"] == "claim_conflict_detection_exception"
    assert failed_events[0]["error"]["message"] == "detector unavailable"


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
