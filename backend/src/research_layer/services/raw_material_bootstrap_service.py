from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore

ALLOWED_BOOTSTRAP_SOURCE_TYPES = {"paper", "note", "feedback", "failure_record", "dialogue"}
ALLOWED_BOOTSTRAP_CANDIDATE_TYPES = {
    "evidence",
    "assumption",
    "conflict",
    "failure",
    "validation",
}


class RawMaterialBootstrapService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def bootstrap(
        self,
        *,
        workspace_id: str,
        materials: list[dict[str, object]],
        request_id: str,
        run_extract: bool,
    ) -> dict[str, object]:
        imported: list[dict[str, object]] = []
        failed: list[dict[str, object]] = []
        for index, material in enumerate(materials):
            try:
                imported.append(
                    self._import_one(
                        workspace_id=workspace_id,
                        material=material,
                        request_id=request_id,
                        run_extract=run_extract,
                    )
                )
            except ValueError as exc:
                failed.append(
                    {
                        "index": index,
                        "error": {
                            "error_code": "research.invalid_request",
                            "message": str(exc),
                            "details": {"index": index},
                        },
                    }
                )
        if not failed:
            status = "succeeded"
            event_status = "completed"
        elif imported:
            status = "partial"
            event_status = "degraded"
        else:
            status = "failed"
            event_status = "failed"
        self._store.emit_event(
            event_name="sources_bootstrap_completed",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="raw_material_bootstrap_service",
            step="bootstrap",
            status=event_status,
            refs={
                "source_ids": [item["source_id"] for item in imported],
                "candidate_ids": [
                    candidate_id
                    for item in imported
                    for candidate_id in item.get("candidate_ids", [])
                ],
                "job_ids": [
                    job_ref["job_id"]
                    for item in imported
                    for job_ref in item.get("job_refs", [])
                ],
            },
            metrics={
                "imported_count": len(imported),
                "failed_count": len(failed),
                "run_extract": run_extract,
            },
            error=(
                None
                if event_status != "failed"
                else {
                    "error_code": "research.invalid_request",
                    "message": "all bootstrap materials failed validation",
                    "details": {"failed_count": len(failed)},
                }
            ),
        )
        return {
            "workspace_id": workspace_id,
            "status": status,
            "imported_count": len(imported),
            "failed_count": len(failed),
            "items": imported,
            "failures": failed,
        }

    def _import_one(
        self,
        *,
        workspace_id: str,
        material: dict[str, object],
        request_id: str,
        run_extract: bool,
    ) -> dict[str, object]:
        source_type = str(material.get("source_type", "")).strip()
        title = str(material.get("title", "")).strip()
        content = str(material.get("content", "")).strip()
        if source_type not in ALLOWED_BOOTSTRAP_SOURCE_TYPES:
            raise ValueError("unsupported source_type")
        if not title:
            raise ValueError("title is required")
        if not content:
            raise ValueError("content is required")
        metadata = material.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        source = self._store.create_source(
            workspace_id=workspace_id,
            source_type=source_type,
            title=title,
            content=content,
            metadata={
                **metadata,
                "bootstrap_provenance": material.get("provenance", {}),
            },
            import_request_id=request_id,
        )

        candidate_ids: list[str] = []
        candidates = material.get("candidates")
        if isinstance(candidates, list) and candidates:
            job = self._store.create_job(
                job_type="source_bootstrap_candidates",
                workspace_id=workspace_id,
                request_id=request_id,
            )
            batch = self._store.create_candidate_batch(
                workspace_id=workspace_id,
                source_id=str(source["source_id"]),
                job_id=str(job["job_id"]),
                request_id=request_id,
            )
            created = self._store.add_candidates_to_batch(
                candidate_batch_id=str(batch["candidate_batch_id"]),
                workspace_id=workspace_id,
                source_id=str(source["source_id"]),
                job_id=str(job["job_id"]),
                candidates=[
                    self._normalize_candidate(candidate, index=index)
                    for index, candidate in enumerate(candidates)
                ],
            )
            candidate_ids = [str(item["candidate_id"]) for item in created]
            self._store.finish_job_success(
                job_id=str(job["job_id"]),
                result_ref={
                    "resource_type": "candidate_batch",
                    "resource_id": str(batch["candidate_batch_id"]),
                },
            )

        job_refs: list[dict[str, str]] = []
        if run_extract:
            job = self._store.create_job(
                job_type="source_extract",
                workspace_id=workspace_id,
                request_id=request_id,
            )
            job_refs.append(
                {
                    "job_id": str(job["job_id"]),
                    "job_type": str(job["job_type"]),
                    "status": str(job["status"]),
                }
            )

        return {
            "source_id": str(source["source_id"]),
            "candidate_ids": candidate_ids,
            "provenance": material.get("provenance", {}),
            "job_refs": job_refs,
        }

    def _normalize_candidate(
        self, candidate: object, *, index: int
    ) -> dict[str, object]:
        if not isinstance(candidate, dict):
            raise ValueError(f"candidate[{index}] must be object")
        candidate_type = str(candidate.get("candidate_type", "")).strip()
        text = str(candidate.get("text", "")).strip()
        if candidate_type not in ALLOWED_BOOTSTRAP_CANDIDATE_TYPES:
            raise ValueError(f"candidate[{index}] has unsupported candidate_type")
        if not text:
            raise ValueError(f"candidate[{index}] text is required")
        source_span = candidate.get("source_span")
        if not isinstance(source_span, dict):
            source_span = {"start": 0, "end": len(text)}
        return {
            "candidate_type": candidate_type,
            "text": text,
            "source_span": source_span,
            "extractor_name": "raw_material_bootstrap",
        }
