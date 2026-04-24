from __future__ import annotations

import json
import os
import re
from json import JSONDecodeError
from types import SimpleNamespace

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.extractors import (
    AssumptionExtractor,
    ConflictExtractor,
    EvidenceExtractor,
    FailureExtractor,
    ValidationExtractor,
)
from research_layer.extractors.types import ExtractFailureError
from research_layer.services.argument_unit_extraction_service import (
    ArgumentUnitExtractionService,
)
from research_layer.services.llm_gateway import ResearchLLMError
from research_layer.services.llm_trace import LLMCallResult, build_event_trace_parts
from research_layer.services.prompt_renderer import (
    build_messages_from_prompt,
    load_prompt_template,
    render_prompt_template,
)
from research_layer.services.research_llm_dependencies import (
    build_research_llm_gateway,
    resolve_research_backend_and_model,
)
from research_layer.services.relation_extraction_service import RelationExtractionService
from research_layer.services.source_chunking_service import SourceChunk, SourceChunkingService
from research_layer.services.source_parser import (
    ParseFailureError,
    ParsedSegment,
    ParsedSource,
    SourceParser,
)

_EXTRACTION_FALLBACK_ALLOWED_ERRORS = {
    "research.llm_failed",
    "research.llm_timeout",
    "research.llm_invalid_output",
}
_DEFAULT_EXTRACTION_MAX_INPUT_CHARS = 120000
_DEFAULT_EXTRACTION_MAX_INPUT_SEGMENTS = 400
_DEFAULT_EXTRACTION_MAX_OUTPUT_TOKENS = 12000
_DEFAULT_EXTRACTION_LLM_TIMEOUT_SECONDS = 300
_DEFAULT_DOCUMENT_READER_MAX_OUTPUT_TOKENS = 1800
_DEFAULT_SOURCE_CHUNK_MAX_CHARS = 50000
_DEFAULT_SOURCE_CHUNK_MAX_SEGMENTS = 1000
_MIN_EXTRACTION_CANDIDATE_COUNT = 3
_MIN_EXTRACTION_TYPE_DIVERSITY = 2
_MAX_CANDIDATE_TEXT_CHARS = 220


def _strip_llm_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _normalized_usage(usage: object | None) -> dict[str, int]:
    raw = usage if isinstance(usage, dict) else {}
    prompt_tokens = raw.get("prompt_tokens")
    completion_tokens = raw.get("completion_tokens")
    total_tokens = raw.get("total_tokens")

    def _as_int(value: object | None) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return max(value, 0)
        if isinstance(value, float):
            return max(int(value), 0)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped)
        return 0

    normalized_prompt = _as_int(prompt_tokens)
    normalized_completion = _as_int(completion_tokens)
    normalized_total = _as_int(total_tokens)
    if normalized_total == 0:
        normalized_total = normalized_prompt + normalized_completion
    return {
        "prompt_tokens": normalized_prompt,
        "completion_tokens": normalized_completion,
        "total_tokens": normalized_total,
    }


def _read_positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class ExtractionWorker:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._parser = SourceParser()
        self._gateway = build_research_llm_gateway()
        self._chunking = SourceChunkingService(
            max_chars=_read_positive_int_env(
                "RESEARCH_SOURCE_CHUNK_MAX_CHARS",
                _DEFAULT_SOURCE_CHUNK_MAX_CHARS,
            ),
            max_segments=_read_positive_int_env(
                "RESEARCH_SOURCE_CHUNK_MAX_SEGMENTS",
                _DEFAULT_SOURCE_CHUNK_MAX_SEGMENTS,
            ),
        )
        self._extractors = (
            EvidenceExtractor(),
            AssumptionExtractor(),
            ConflictExtractor(),
            FailureExtractor(),
            ValidationExtractor(),
        )

    async def run(
        self,
        *,
        request_id: str,
        job_id: str,
        workspace_id: str,
        source_id: str,
        failure_mode: str | None = None,
        allow_fallback: bool = False,
    ) -> dict[str, object]:
        source = self._store.get_source(source_id)
        if source is None:
            error = {
                "error_code": "research.not_found",
                "message": "source not found",
                "details": {"source_id": source_id, "job_id": job_id},
            }
            self._store.finish_job_failed(job_id=job_id, error=error)
            return {"status": "failed", "error": error}

        self._store.start_job(job_id)
        batch = self._store.create_candidate_batch(
            workspace_id=workspace_id,
            source_id=source_id,
            job_id=job_id,
            request_id=request_id,
        )
        batch_id = str(batch["candidate_batch_id"])

        self._store.emit_event(
            event_name="candidate_extraction_started",
            request_id=request_id,
            job_id=job_id,
            workspace_id=workspace_id,
            source_id=source_id,
            candidate_batch_id=batch_id,
            component="extraction_worker",
            step="extract",
            status="started",
            refs={"source_id": source_id, "candidate_batch_id": batch_id},
        )
        try:
            parsed = self._parser.parse(
                source_type=str(source["source_type"]),
                content=str(source["content"]),
                metadata=source.get("metadata")
                if isinstance(source.get("metadata"), dict)
                else None,
            )
            self._store.update_source_processing(
                source_id=source_id,
                status="parsed",
                normalized_content=parsed.normalized_content,
                last_extract_job_id=job_id,
            )
            self._store.replace_source_artifacts(
                workspace_id=workspace_id,
                source_id=source_id,
                artifacts=self._build_source_artifacts(
                    workspace_id=workspace_id,
                    source_id=source_id,
                    parsed=parsed,
                ),
            )
            raw_candidates: list[dict[str, object]] = []
            latest_trace: LLMCallResult | None = None
            degraded = False
            fallback_used = False
            degraded_reason: str | None = None
            partial_failure_count = 0
            raw_relations: list[dict[str, object]] = []

            try:
                chunk_plan = self._chunking.plan(
                    source_id=str(source["source_id"]), parsed=parsed
                )
                self._store.emit_event(
                    event_name="candidate_extraction_progress",
                    request_id=request_id,
                    job_id=job_id,
                    workspace_id=workspace_id,
                    source_id=source_id,
                    candidate_batch_id=batch_id,
                    component="extraction_worker",
                    step="chunk_plan",
                    status="completed",
                    refs={"candidate_batch_id": batch_id},
                    metrics={"chunk_count": len(chunk_plan.chunks)},
                )
                self._store.emit_event(
                    event_name="candidate_extraction_progress",
                    request_id=request_id,
                    job_id=job_id,
                    workspace_id=workspace_id,
                    source_id=source_id,
                    candidate_batch_id=batch_id,
                    component="extraction_worker",
                    step="document_reader",
                    status="started",
                    refs={"candidate_batch_id": batch_id},
                )
                document_reading_memo = await self._build_document_reading_memo(
                    request_id=request_id,
                    parsed=parsed,
                    failure_mode=failure_mode,
                )
                self._store.emit_event(
                    event_name="candidate_extraction_progress",
                    request_id=request_id,
                    job_id=job_id,
                    workspace_id=workspace_id,
                    source_id=source_id,
                    candidate_batch_id=batch_id,
                    component="extraction_worker",
                    step="document_reader",
                    status="completed",
                    refs={"candidate_batch_id": batch_id},
                )
                backend, model = resolve_research_backend_and_model()
                for chunk in chunk_plan.chunks:
                    self._store.emit_event(
                        event_name="candidate_extraction_progress",
                        request_id=request_id,
                        job_id=job_id,
                        workspace_id=workspace_id,
                        source_id=source_id,
                        candidate_batch_id=batch_id,
                        component="extraction_worker",
                        step="argument_unit_extraction",
                        status="started",
                        refs={
                            "candidate_batch_id": batch_id,
                            "chunk_id": chunk.chunk_id,
                        },
                        metrics={
                            "chunk_index": chunk.chunk_index,
                            "chunk_count": len(chunk_plan.chunks),
                        },
                    )
                    try:
                        units, mapped_candidates, unit_trace = (
                            await self._extract_argument_units_for_chunk(
                                request_id=request_id,
                                workspace_id=workspace_id,
                                source=source,
                                parsed=parsed,
                                chunk=chunk,
                                document_reading_memo=document_reading_memo,
                                failure_mode=failure_mode,
                                backend=backend,
                                model=model,
                            )
                        )
                    except ResearchLLMError as exc:
                        degraded = True
                        degraded_reason = degraded_reason or exc.error_code
                        partial_failure_count += 1
                        self._store.emit_event(
                            event_name="candidate_extraction_progress",
                            request_id=request_id,
                            job_id=job_id,
                            workspace_id=workspace_id,
                            source_id=source_id,
                            candidate_batch_id=batch_id,
                            component="extraction_worker",
                            step="argument_unit_extraction",
                            status="failed",
                            refs={
                                "candidate_batch_id": batch_id,
                                "chunk_id": chunk.chunk_id,
                            },
                            metrics={
                                "chunk_index": chunk.chunk_index,
                                "chunk_count": len(chunk_plan.chunks),
                            },
                            error={
                                "error_code": exc.error_code,
                                "message": exc.message,
                                "details": exc.details,
                            },
                        )
                        continue
                    raw_candidates.extend(mapped_candidates)
                    if unit_trace is not None:
                        latest_trace = unit_trace
                    self._store.emit_event(
                        event_name="candidate_extraction_progress",
                        request_id=request_id,
                        job_id=job_id,
                        workspace_id=workspace_id,
                        source_id=source_id,
                        candidate_batch_id=batch_id,
                        component="extraction_worker",
                        step="argument_unit_extraction",
                        status="completed",
                        refs={
                            "candidate_batch_id": batch_id,
                            "chunk_id": chunk.chunk_id,
                        },
                        metrics={
                            "chunk_index": chunk.chunk_index,
                            "chunk_count": len(chunk_plan.chunks),
                            "unit_count": len(units),
                            "candidate_count": len(mapped_candidates),
                        },
                    )
                    if not units:
                        continue
                    self._store.emit_event(
                        event_name="candidate_extraction_progress",
                        request_id=request_id,
                        job_id=job_id,
                        workspace_id=workspace_id,
                        source_id=source_id,
                        candidate_batch_id=batch_id,
                        component="extraction_worker",
                        step="argument_relation_rebuild",
                        status="started",
                        refs={
                            "candidate_batch_id": batch_id,
                            "chunk_id": chunk.chunk_id,
                        },
                        metrics={
                            "chunk_index": chunk.chunk_index,
                            "chunk_count": len(chunk_plan.chunks),
                            "unit_count": len(units),
                        },
                    )
                    try:
                        relations, relation_trace = await RelationExtractionService(
                            self._gateway
                        ).rebuild_relations(
                            request_id=request_id,
                            workspace_id=workspace_id,
                            source_id=str(source["source_id"]),
                            units=units,
                            chunk_text=chunk.text,
                            max_tokens=self._resolve_output_max_tokens(),
                            timeout_s=self._resolve_llm_timeout_seconds(),
                            failure_mode=failure_mode,
                            backend=backend,
                            model=model,
                        )
                    except ResearchLLMError as exc:
                        degraded = True
                        degraded_reason = degraded_reason or exc.error_code
                        partial_failure_count += 1
                        self._store.emit_event(
                            event_name="candidate_extraction_progress",
                            request_id=request_id,
                            job_id=job_id,
                            workspace_id=workspace_id,
                            source_id=source_id,
                            candidate_batch_id=batch_id,
                            component="extraction_worker",
                            step="argument_relation_rebuild",
                            status="failed",
                            refs={
                                "candidate_batch_id": batch_id,
                                "chunk_id": chunk.chunk_id,
                            },
                            metrics={
                                "chunk_index": chunk.chunk_index,
                                "chunk_count": len(chunk_plan.chunks),
                                "unit_count": len(units),
                            },
                            error={
                                "error_code": exc.error_code,
                                "message": exc.message,
                                "details": exc.details,
                            },
                        )
                        continue
                    raw_relations.extend(relations)
                    latest_trace = relation_trace
                    self._store.emit_event(
                        event_name="candidate_extraction_progress",
                        request_id=request_id,
                        job_id=job_id,
                        workspace_id=workspace_id,
                        source_id=source_id,
                        candidate_batch_id=batch_id,
                        component="extraction_worker",
                        step="argument_relation_rebuild",
                        status="completed",
                        refs={
                            "candidate_batch_id": batch_id,
                            "chunk_id": chunk.chunk_id,
                        },
                        metrics={
                            "chunk_index": chunk.chunk_index,
                            "chunk_count": len(chunk_plan.chunks),
                            "relation_count": len(relations),
                        },
                    )
            except ResearchLLMError as exc:
                if allow_fallback and exc.error_code in _EXTRACTION_FALLBACK_ALLOWED_ERRORS:
                    fallback_used = True
                    degraded = True
                    degraded_reason = exc.error_code
                    partial_failure_count += 1
                else:
                    raise

            if not allow_fallback and not raw_candidates and partial_failure_count > 0:
                raise ResearchLLMError(
                    status_code=504 if degraded_reason == "research.llm_timeout" else 502,
                    error_code=degraded_reason or "research.llm_failed",
                    message="all extraction chunks failed",
                    details={"partial_failure_count": partial_failure_count},
                )

            raw_candidates = self._dedupe_candidates(raw_candidates)
            if fallback_used and not raw_candidates:
                raw_candidates.append(
                    self._build_minimal_fallback_candidate(
                        source=source,
                        parsed=parsed,
                        request_id=request_id,
                        degraded_reason=degraded_reason,
                    )
                )
            if fallback_used and len(raw_candidates) < 2:
                raw_candidates.extend(
                    self._build_supplemental_fallback_candidates(
                        parsed=parsed,
                        request_id=request_id,
                        degraded_reason=degraded_reason,
                        existing_candidates=raw_candidates,
                        minimum_count=2,
                    )
                )
            if fallback_used and len(raw_candidates) < 5:
                raw_candidates.extend(
                    self._build_supplemental_fallback_candidates(
                        parsed=parsed,
                        request_id=request_id,
                        degraded_reason=degraded_reason,
                        existing_candidates=raw_candidates,
                        minimum_count=5,
                    )
                )
            candidate_type_count = len(
                {
                    str(item.get("candidate_type", "")).strip()
                    for item in raw_candidates
                    if isinstance(item, dict)
                }
            )
            if allow_fallback and (
                len(raw_candidates) < _MIN_EXTRACTION_CANDIDATE_COUNT
                or candidate_type_count < _MIN_EXTRACTION_TYPE_DIVERSITY
            ):
                supplemental_candidates = self._build_supplemental_fallback_candidates(
                    parsed=parsed,
                    request_id=request_id,
                    degraded_reason=degraded_reason or "research.extraction_underfilled",
                    existing_candidates=raw_candidates,
                    minimum_count=_MIN_EXTRACTION_CANDIDATE_COUNT,
                )
                if supplemental_candidates:
                    raw_candidates.extend(supplemental_candidates)
                    fallback_used = True
                    degraded = True
                    degraded_reason = degraded_reason or "research.extraction_underfilled"
                    partial_failure_count += 1
            raw_candidates = self._dedupe_candidates(raw_candidates)

            normalized_trace_usage = _normalized_usage(
                latest_trace.usage if latest_trace is not None else None
            )
            persisted = self._store.add_candidates_to_batch(
                candidate_batch_id=batch_id,
                workspace_id=workspace_id,
                source_id=source_id,
                job_id=job_id,
                candidates=raw_candidates,
                llm_trace=(
                    {
                        "provider_backend": latest_trace.provider_backend,
                        "provider_model": latest_trace.provider_model,
                        "request_id": latest_trace.request_id,
                        "llm_response_id": latest_trace.llm_response_id,
                        "usage": normalized_trace_usage,
                        "fallback_used": latest_trace.fallback_used or fallback_used,
                        "degraded": latest_trace.degraded or degraded,
                        "degraded_reason": degraded_reason or latest_trace.degraded_reason,
                    }
                    if latest_trace
                    else None
                ),
            )
            unit_candidate_ids = {
                str((item.get("trace_refs") or {}).get("argument_unit_id") or ""): str(
                    item["candidate_id"]
                )
                for item in persisted
                if isinstance(item.get("trace_refs"), dict)
            }
            relation_candidates = self._map_relations_to_candidates(
                relations=raw_relations,
                unit_candidate_ids=unit_candidate_ids,
            )
            if relation_candidates:
                self._store.add_relation_candidates_to_batch(
                    candidate_batch_id=batch_id,
                    workspace_id=workspace_id,
                    source_id=source_id,
                    job_id=job_id,
                    relations=relation_candidates,
                )
            self._store.update_candidate_batch_llm_trace(
                candidate_batch_id=batch_id,
                provider_backend=(
                    latest_trace.provider_backend
                    if latest_trace
                    else self._resolve_backend_hint()
                ),
                provider_model=(
                    latest_trace.provider_model
                    if latest_trace
                    else ("fallback_parser" if fallback_used else None)
                ),
                llm_request_id=request_id,
                llm_response_id=(
                    latest_trace.llm_response_id
                    if latest_trace and latest_trace.llm_response_id
                    else (request_id if fallback_used else None)
                ),
                usage=normalized_trace_usage if (latest_trace or fallback_used) else None,
                fallback_used=fallback_used or (latest_trace.fallback_used if latest_trace else False),
                degraded=degraded or (latest_trace.degraded if latest_trace else False),
                degraded_reason=degraded_reason or (latest_trace.degraded_reason if latest_trace else None),
                partial_failure_count=partial_failure_count,
            )
            self._store.update_source_processing(
                source_id=source_id,
                status="extracted",
                normalized_content=parsed.normalized_content,
                last_extract_job_id=job_id,
            )
            self._store.finish_job_success(
                job_id=job_id,
                result_ref={"resource_type": "candidate_batch", "resource_id": batch_id},
            )
            refs = {"candidate_batch_id": batch_id}
            metrics = {"candidate_count": len(persisted)}
            if latest_trace is not None:
                trace_refs, trace_metrics = build_event_trace_parts(latest_trace)
                refs.update(trace_refs)
                metrics.update(trace_metrics)
            metrics["fallback_used"] = bool(metrics.get("fallback_used") or fallback_used)
            metrics["degraded"] = bool(metrics.get("degraded") or degraded)
            if "chunk_plan" in locals():
                metrics["chunk_count"] = len(chunk_plan.chunks)
            if degraded_reason:
                metrics["degraded_reason"] = degraded_reason
            metrics["partial_failure_count"] = partial_failure_count
            self._store.emit_event(
                event_name="candidate_extraction_completed",
                request_id=request_id,
                job_id=job_id,
                workspace_id=workspace_id,
                source_id=source_id,
                candidate_batch_id=batch_id,
                component="extraction_worker",
                step="extract",
                status="completed",
                refs=refs,
                metrics=metrics,
            )
            return {"status": "succeeded", "candidate_batch_id": batch_id}
        except ParseFailureError as exc:
            error = {
                "error_code": "research.source_import_parse_failed",
                "message": str(exc),
                "details": {"source_id": source_id, "job_id": job_id},
            }
        except ExtractFailureError as exc:
            error = {
                "error_code": "research.extract_failure",
                "message": str(exc),
                "details": {"source_id": source_id, "extractor": exc.extractor},
            }
        except ResearchLLMError as exc:
            error = {
                "error_code": exc.error_code,
                "message": exc.message,
                "details": {"source_id": source_id, **exc.details},
            }
        except Exception as exc:  # pragma: no cover - defensive fallback
            error = {
                "error_code": "research.extract_failure",
                "message": "unexpected extraction failure",
                "details": {"source_id": source_id, "reason": str(exc)},
            }

        details = error.get("details")
        if not isinstance(details, dict):
            details = {}
            error["details"] = details
        details["source_id"] = source_id
        details["job_id"] = job_id
        details["candidate_batch_id"] = batch_id
        self._store.fail_candidate_batch(candidate_batch_id=batch_id, error=error)
        self._store.finish_job_failed(job_id=job_id, error=error)
        self._store.update_source_processing(
            source_id=source_id,
            status="extract_failed",
            last_extract_job_id=job_id,
        )
        self._store.emit_event(
            event_name="candidate_extraction_failed",
            request_id=request_id,
            job_id=job_id,
            workspace_id=workspace_id,
            source_id=source_id,
            candidate_batch_id=batch_id,
            component="extraction_worker",
            step="extract",
            status="failed",
            refs={"candidate_batch_id": batch_id},
            error=error,
        )
        self._store.emit_event(
            event_name="candidate_extraction_completed",
            request_id=request_id,
            job_id=job_id,
            workspace_id=workspace_id,
            source_id=source_id,
            candidate_batch_id=batch_id,
            component="extraction_worker",
            step="extract",
            status="failed",
            refs={"candidate_batch_id": batch_id},
            error=error,
        )
        self._store.emit_event(
            event_name="job_failed",
            request_id=request_id,
            job_id=job_id,
            workspace_id=workspace_id,
            source_id=source_id,
            candidate_batch_id=batch_id,
            component="extraction_worker",
            step="extract",
            status="failed",
            refs={"candidate_batch_id": batch_id},
            error=error,
        )
        return {"status": "failed", "candidate_batch_id": batch_id, "error": error}

    def _map_relations_to_candidates(
        self,
        *,
        relations: list[dict[str, object]],
        unit_candidate_ids: dict[str, str],
    ) -> list[dict[str, object]]:
        mapped: list[dict[str, object]] = []
        for relation in relations:
            source_unit_id = str(relation.get("source_unit_id") or "")
            target_unit_id = str(relation.get("target_unit_id") or "")
            source_candidate_id = unit_candidate_ids.get(source_unit_id)
            target_candidate_id = unit_candidate_ids.get(target_unit_id)
            if source_candidate_id is None or target_candidate_id is None:
                mapped.append(
                    {
                        "source_candidate_id": source_candidate_id,
                        "target_candidate_id": target_candidate_id,
                        "semantic_relation_type": relation.get("semantic_relation_type"),
                        "relation_type": relation.get("relation_type"),
                        "relation_status": "unresolved",
                        "quote": relation.get("quote"),
                        "trace_refs": {
                            "source_unit_id": source_unit_id,
                            "target_unit_id": target_unit_id,
                            "confidence_label": relation.get("confidence_label"),
                            "confidence_score": relation.get("confidence_score"),
                        },
                    }
                )
                continue
            mapped.append(
                {
                    "source_candidate_id": source_candidate_id,
                    "target_candidate_id": target_candidate_id,
                    "semantic_relation_type": relation.get("semantic_relation_type"),
                    "relation_type": relation.get("relation_type"),
                    "relation_status": relation.get("relation_status") or "unresolved",
                    "quote": relation.get("quote"),
                    "trace_refs": {
                        "source_unit_id": source_unit_id,
                        "target_unit_id": target_unit_id,
                        "confidence_label": relation.get("confidence_label"),
                        "confidence_score": relation.get("confidence_score"),
                    },
                }
            )
        return mapped

    def _map_argument_units_to_candidates(
        self,
        *,
        units: list[dict[str, object]],
        source_id: str,
        parsed: ParsedSource,
        trace: LLMCallResult,
        request_id: str,
    ) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for unit in units:
            quote = str(unit.get("quote") or unit.get("text") or "").strip()
            text = self._normalize_candidate_text(str(unit.get("text") or quote))
            if not text:
                continue
            start, end, matched_span_text = self._resolve_source_span(
                parsed=parsed,
                primary_query=quote,
                secondary_query=text,
            )
            if start < 0 or end <= start:
                continue
            source_span = self._build_source_span(
                parsed=parsed,
                start=start,
                end=end,
                matched_span_text=matched_span_text,
            )
            artifact_id = self._artifact_id_for_span(source_id=source_id, span=source_span)
            candidates.append(
                {
                    "candidate_type": str(unit.get("candidate_type") or ""),
                    "semantic_type": str(unit.get("semantic_type") or ""),
                    "text": text,
                    "quote": quote or matched_span_text,
                    "source_span": source_span,
                    "trace_refs": {
                        "argument_unit_id": str(unit.get("unit_id") or ""),
                        "domain_profile": unit.get("domain_profile") or [],
                        "domain_tags": unit.get("domain_tags") or [],
                        "normalized_label": str(unit.get("normalized_label") or ""),
                        "confidence_score": unit.get("confidence_score"),
                        "source_artifact_id": artifact_id,
                        "source_anchor_id": source_span.get("block_id")
                        or source_span.get("paragraph_id"),
                    },
                    "extractor_name": "argument_unit_extractor",
                    "provider_backend": trace.provider_backend,
                    "provider_model": trace.provider_model,
                    "request_id": trace.request_id or request_id,
                    "llm_response_id": trace.llm_response_id,
                    "usage": trace.usage,
                    "fallback_used": trace.fallback_used,
                    "degraded": trace.degraded,
                    "degraded_reason": trace.degraded_reason,
                }
            )
        return candidates

    async def _extract_argument_units_for_chunk(
        self,
        *,
        request_id: str,
        workspace_id: str,
        source: dict[str, object],
        parsed: ParsedSource,
        chunk: SourceChunk,
        document_reading_memo: dict[str, object] | None,
        failure_mode: str | None,
        backend: str | None,
        model: str | None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], LLMCallResult | None]:
        source_id = str(source["source_id"])
        cache_key = "candidate:argument_unit_extractor:v6_numbered_hypotheses"
        cached = self._store.get_source_chunk_cache(
            workspace_id=workspace_id,
            source_id=source_id,
            chunk_hash=chunk.chunk_hash,
            cache_key=cache_key,
        )
        if cached is not None:
            payload = cached.get("payload", {})
            units = payload.get("units", []) if isinstance(payload, dict) else []
            candidates = payload.get("candidates", []) if isinstance(payload, dict) else []
            return (
                [dict(item) for item in units if isinstance(item, dict)],
                [dict(item) for item in candidates if isinstance(item, dict)],
                None,
            )

        anchor_refs = self._build_anchor_refs_for_chunk(parsed=parsed, chunk=chunk)
        artifact_profile = self._build_chunk_artifact_profile(
            parsed=parsed, chunk=chunk, anchor_refs=anchor_refs
        )
        units, trace = await ArgumentUnitExtractionService(self._gateway).extract_units(
            request_id=request_id,
            workspace_id=workspace_id,
            source_id=source_id,
            source_title=str(source["title"]),
            source_type=str(source["source_type"]),
            chunk_id=chunk.chunk_id,
            chunk_section=chunk.section_hint,
            chunk_text=chunk.text,
            anchor_refs=anchor_refs,
            document_reading_memo=json.dumps(
                document_reading_memo or {}, ensure_ascii=False
            ),
            artifact_profile=artifact_profile,
            max_tokens=self._resolve_output_max_tokens(),
            timeout_s=self._resolve_llm_timeout_seconds(),
            failure_mode=failure_mode,
            backend=backend,
            model=model,
        )
        mapped = self._map_argument_units_to_candidates(
            units=units,
            source_id=source_id,
            parsed=parsed,
            trace=trace,
            request_id=request_id,
        )
        for candidate in mapped:
            trace_refs = candidate.get("trace_refs")
            if not isinstance(trace_refs, dict):
                trace_refs = {}
                candidate["trace_refs"] = trace_refs
            trace_refs["chunk_id"] = chunk.chunk_id
            trace_refs["chunk_hash"] = chunk.chunk_hash
        self._store.upsert_source_chunk_cache(
            workspace_id=workspace_id,
            source_id=source_id,
            chunk_hash=chunk.chunk_hash,
            cache_key=cache_key,
            payload={"units": units, "candidates": mapped},
        )
        return units, mapped, trace

    def _build_source_span(
        self,
        *,
        parsed: ParsedSource,
        start: int,
        end: int,
        matched_span_text: str,
    ) -> dict[str, object]:
        source_span: dict[str, object] = {
            "start": start,
            "end": end,
            "text": matched_span_text,
        }
        for segment in parsed.segments:
            if int(segment.start) <= start and int(segment.end) >= end:
                if segment.page is not None:
                    source_span["page"] = segment.page
                if segment.block_id:
                    source_span["block_id"] = segment.block_id
                if segment.paragraph_id:
                    source_span["paragraph_id"] = segment.paragraph_id
                if segment.section_path:
                    source_span["section_path"] = list(segment.section_path)
                break
        return source_span

    def _build_source_artifacts(
        self, *, workspace_id: str, source_id: str, parsed: ParsedSource
    ) -> list[dict[str, object]]:
        artifacts: list[dict[str, object]] = []
        seen: set[str] = set()
        for segment in parsed.segments:
            anchor_id = str(segment.block_id or segment.paragraph_id or "").strip()
            if not anchor_id or anchor_id in seen:
                continue
            seen.add(anchor_id)
            content = str(segment.text or "").strip()
            if not content:
                continue
            raw_content = str(
                getattr(segment, "raw_text", None) or segment.text or ""
            ).strip()
            artifact_type = str(
                getattr(segment, "artifact_type", None)
                or self._classify_source_artifact(content)
            )
            structure = self._extract_artifact_structure(
                artifact_type=artifact_type,
                content=content,
                raw_content=raw_content,
            )
            metadata = {"source_type": parsed.source_type}
            if structure:
                metadata["structure"] = structure
            artifacts.append(
                {
                    "artifact_id": self._artifact_id_for_anchor(
                        source_id=source_id, anchor_id=anchor_id
                    ),
                    "workspace_id": workspace_id,
                    "source_id": source_id,
                    "artifact_type": artifact_type,
                    "anchor_id": anchor_id,
                    "page": segment.page,
                    "block_id": segment.block_id,
                    "paragraph_id": segment.paragraph_id,
                    "section_path": list(segment.section_path),
                    "content": raw_content if artifact_type != "text" else content,
                    "locator": {
                        "start": segment.start,
                        "end": segment.end,
                        "page": segment.page,
                        "block_id": segment.block_id,
                        "paragraph_id": segment.paragraph_id,
                    },
                    "metadata": metadata,
                }
            )
        return artifacts

    def _classify_source_artifact(self, text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return "text"
        if self._looks_like_table_artifact(stripped):
            return "table"
        if re.search(r"^(图|Figure|Fig\.?)\s*[\d一二三四五六七八九十]", stripped, re.I):
            return "figure"
        if re.search(r"^(表|Table)\s*[\d一二三四五六七八九十]", stripped, re.I):
            return "caption"
        if re.search(
            r"^[（(]?\d+[）)]?\s*[=≈∑∫√]|[=≈]\s*[-+]?\d|[=≈].*(∑|∫|√|∇|Δ|α|β|γ|η|λ|μ|σ|θ|π|x_[{(]|[A-Za-z]\()",
            stripped,
        ):
            return "formula"
        if self._looks_like_code_artifact(stripped):
            return "code"
        return "text"

    def _looks_like_table_artifact(self, text: str) -> bool:
        if "\t" in text or "|" in text:
            return True
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) >= 3:
            numeric_lines = sum(1 for line in lines if len(re.findall(r"\d", line)) >= 2)
            return numeric_lines >= 2
        tokens = text.split()
        numeric_tokens = sum(1 for token in tokens if re.search(r"\d", token))
        return len(tokens) >= 8 and numeric_tokens >= 4

    def _looks_like_code_artifact(self, text: str) -> bool:
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            return False
        marker_count = sum(
            1
            for line in lines
            if re.search(
                r"(def |class |return |if |else:|for |while |\{|\}|=>|#include|public |private |const |let |var |import )",
                line,
            )
        )
        return marker_count >= 2

    def _artifact_id_for_span(
        self, *, source_id: str, span: dict[str, object]
    ) -> str | None:
        anchor_id = str(span.get("block_id") or span.get("paragraph_id") or "").strip()
        if not anchor_id:
            return None
        return self._artifact_id_for_anchor(source_id=source_id, anchor_id=anchor_id)

    def _artifact_id_for_anchor(self, *, source_id: str, anchor_id: str) -> str:
        safe_anchor = re.sub(r"[^A-Za-z0-9_-]+", "_", anchor_id).strip("_")
        return f"art_{source_id}_{safe_anchor}"

    def _build_anchor_refs_for_chunk(
        self, *, parsed: ParsedSource, chunk: SourceChunk
    ) -> list[dict[str, object]]:
        refs: list[dict[str, object]] = []
        for segment in parsed.segments:
            if int(segment.end) < chunk.start or int(segment.start) > chunk.end:
                continue
            ref: dict[str, object] = {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text[:240],
            }
            if segment.page is not None:
                ref["page"] = segment.page
            if segment.block_id:
                ref["block_id"] = segment.block_id
            if segment.paragraph_id:
                ref["paragraph_id"] = segment.paragraph_id
            ref["artifact_type"] = str(
                getattr(segment, "artifact_type", None)
                or self._classify_source_artifact(segment.text)
            )
            refs.append(ref)
            if len(refs) >= 100:
                break
        return refs

    def _build_anchor_refs(self, parsed: ParsedSource) -> list[dict[str, object]]:
        refs: list[dict[str, object]] = []
        for segment in parsed.segments[:100]:
            ref: dict[str, object] = {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text[:240],
            }
            if segment.page is not None:
                ref["page"] = segment.page
            if segment.block_id:
                ref["block_id"] = segment.block_id
            if segment.paragraph_id:
                ref["paragraph_id"] = segment.paragraph_id
            ref["artifact_type"] = str(
                getattr(segment, "artifact_type", None)
                or self._classify_source_artifact(segment.text)
            )
            refs.append(ref)
        return refs

    def _build_chunk_artifact_profile(
        self,
        *,
        parsed: ParsedSource,
        chunk: SourceChunk,
        anchor_refs: list[dict[str, object]],
    ) -> dict[str, object]:
        counts: dict[str, int] = {}
        for ref in anchor_refs:
            artifact_type = str(ref.get("artifact_type") or "text").strip().lower()
            if not artifact_type:
                artifact_type = "text"
            counts[artifact_type] = counts.get(artifact_type, 0) + 1
        dominant_type = "text"
        if counts:
            dominant_type = max(
                counts.items(),
                key=lambda item: (item[1], 0 if item[0] == "text" else 1, item[0]),
            )[0]
        extraction_focus = dominant_type
        if dominant_type == "caption":
            extraction_focus = "figure"
        if len(counts) > 1 and counts.get(dominant_type, 0) < sum(counts.values()):
            extraction_focus = extraction_focus if counts.get(dominant_type, 0) >= 2 else "mixed"
        artifacts: list[dict[str, object]] = []
        seen: set[str] = set()
        for segment in self._iter_chunk_segments(parsed=parsed, chunk=chunk):
            anchor_id = str(segment.block_id or segment.paragraph_id or "").strip()
            if not anchor_id or anchor_id in seen:
                continue
            seen.add(anchor_id)
            artifact_type = str(
                getattr(segment, "artifact_type", None)
                or self._classify_source_artifact(segment.text)
            )
            if artifact_type == "text" and dominant_type != "text":
                continue
            raw_content = str(
                getattr(segment, "raw_text", None) or segment.text or ""
            ).strip()
            structure = self._extract_artifact_structure(
                artifact_type=artifact_type,
                content=str(segment.text or "").strip(),
                raw_content=raw_content,
            )
            artifact_entry: dict[str, object] = {
                "anchor_id": anchor_id,
                "artifact_type": artifact_type,
                "page": segment.page,
                "text_preview": str(segment.text or "").strip()[:200],
            }
            if structure:
                artifact_entry["structure"] = structure
            artifacts.append(artifact_entry)
            if len(artifacts) >= 6:
                break
        return {
            "dominant_artifact_type": dominant_type,
            "extraction_focus": extraction_focus,
            "artifact_counts": counts,
            "artifacts": artifacts,
        }

    def _iter_chunk_segments(
        self, *, parsed: ParsedSource, chunk: SourceChunk
    ) -> list[ParsedSegment]:
        return [
            segment
            for segment in parsed.segments
            if int(segment.end) >= chunk.start and int(segment.start) <= chunk.end
        ]

    def _extract_artifact_structure(
        self,
        *,
        artifact_type: str,
        content: str,
        raw_content: str,
    ) -> dict[str, object]:
        if artifact_type == "table":
            return self._extract_table_structure(raw_content or content)
        if artifact_type == "formula":
            return self._extract_formula_structure(raw_content or content)
        if artifact_type in {"figure", "caption"}:
            return self._extract_figure_structure(raw_content or content)
        if artifact_type == "code":
            return self._extract_code_structure(raw_content or content)
        return {}

    def _extract_table_structure(self, raw_content: str) -> dict[str, object]:
        lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
        if len(lines) <= 1:
            compact_lines = [part.strip() for part in raw_content.split("  ") if part.strip()]
            if len(compact_lines) > 1:
                lines = compact_lines
        if not lines:
            return {}
        rows = [self._split_artifact_cells(line) for line in lines]
        rows = [row for row in rows if row]
        if not rows:
            return {}
        column_count = max(len(row) for row in rows)
        headers = rows[0][:column_count] + [
            f"col_{index + 1}" for index in range(len(rows[0]), column_count)
        ]
        data_rows = rows[1:25]
        normalized_rows: list[dict[str, object]] = []
        for row_index, row in enumerate(data_rows, start=1):
            cells = row[:column_count] + [""] * max(column_count - len(row), 0)
            normalized_rows.append(
                {
                    "row_index": row_index,
                    "cells": cells,
                    "mapping": {
                        headers[col_index] or f"col_{col_index + 1}": cells[col_index]
                        for col_index in range(column_count)
                    },
                }
            )
        numeric_cell_count = sum(
            1 for row in rows for cell in row if re.search(r"\d", cell)
        )
        return {
            "headers": headers,
            "row_count": max(len(rows) - 1, 0),
            "column_count": column_count,
            "rows": normalized_rows,
            "numeric_cell_count": numeric_cell_count,
        }

    def _split_artifact_cells(self, line: str) -> list[str]:
        if "\t" in line:
            return [cell.strip() for cell in line.split("\t") if cell.strip()]
        if "|" in line:
            return [cell.strip() for cell in line.split("|") if cell.strip()]
        cells = [cell.strip() for cell in re.split(r"\s{2,}", line) if cell.strip()]
        if len(cells) >= 2:
            return cells
        return [part.strip() for part in line.split() if part.strip()]

    def _extract_formula_structure(self, raw_content: str) -> dict[str, object]:
        lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
        equations = [
            line
            for line in lines
            if re.search(r"[=≈]", line) or re.search(r"(∑|∫|√|∇|Δ|α|β|γ|η|λ|μ|σ|θ|π)", line)
        ]
        symbols = sorted(
            {
                symbol
                for symbol in re.findall(
                    r"[A-Za-z][A-Za-z0-9_]*|[α-ωΑ-Ω∇Δπσθηλμ]",
                    raw_content,
                )
                if len(symbol) >= 1
            }
        )[:20]
        return {
            "equations": equations[:8],
            "symbol_candidates": symbols,
            "equation_count": len(equations),
        }

    def _extract_figure_structure(self, raw_content: str) -> dict[str, object]:
        stripped = raw_content.strip()
        label_match = re.match(
            r"^((?:图|Figure|Fig\.?|表|Table)\s*[\d一二三四五六七八九十]+[.:：]?)\s*(.*)$",
            stripped,
            re.I,
        )
        if label_match:
            label = label_match.group(1).strip()
            caption_text = label_match.group(2).strip()
        else:
            label = ""
            caption_text = stripped
        return {
            "label": label,
            "caption_text": caption_text,
            "mentions_numbers": bool(re.search(r"\d", stripped)),
        }

    def _extract_code_structure(self, raw_content: str) -> dict[str, object]:
        lines = [line.rstrip() for line in raw_content.splitlines() if line.strip()]
        function_names = re.findall(
            r"(?:def|function|class)\s+([A-Za-z_][A-Za-z0-9_]*)|([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            raw_content,
        )
        normalized_function_names = []
        for direct_name, call_name in function_names:
            candidate = direct_name or call_name
            if candidate and candidate not in normalized_function_names:
                normalized_function_names.append(candidate)
        return {
            "language_hint": self._guess_code_language(raw_content),
            "line_count": len(lines),
            "function_names": normalized_function_names[:12],
        }

    def _guess_code_language(self, raw_content: str) -> str:
        if re.search(r"#include\s+<", raw_content):
            return "c_cpp"
        if re.search(r"\bdef\s+[A-Za-z_][A-Za-z0-9_]*\s*\(", raw_content):
            return "python"
        if re.search(r"\bfunction\s+[A-Za-z_][A-Za-z0-9_]*\s*\(", raw_content):
            return "javascript"
        if "public class " in raw_content or "private " in raw_content:
            return "java_like"
        return "unknown"

    async def _extract_via_llm(
        self,
        *,
        extractor: object,
        request_id: str,
        workspace_id: str,
        source: dict[str, object],
        parsed: ParsedSource,
        failure_mode: str | None,
    ) -> tuple[list[dict[str, object]], LLMCallResult]:
        normalized_content = parsed.normalized_content
        prompt_chunk = self._build_prompt_chunk(parsed)
        prompt_template = load_prompt_template(getattr(extractor, "prompt_file_name"))
        prompt = render_prompt_template(
            prompt_template,
            {
                "workspace_id": workspace_id,
                "source_id": str(source["source_id"]),
                "source_title": str(source["title"]),
                "source_type": str(source["source_type"]),
                "chunk_id": f"chunk_{source['source_id']}",
                "chunk_index": 0,
                "chunk_section": "full",
                "chunk_text": prompt_chunk,
            },
        )
        backend, model = resolve_research_backend_and_model()
        result = await self._gateway.invoke_json(
            request_id=request_id,
            prompt_name=f"extraction_{getattr(extractor, 'extractor_name', 'unknown')}",
            messages=build_messages_from_prompt(prompt),
            backend=backend,
            model=model,
            max_tokens=self._resolve_output_max_tokens(),
            timeout_s=self._resolve_llm_timeout_seconds(),
            allow_fallback=False,
            expected_container="dict",
            failure_mode=failure_mode,
        )
        payload = result.parsed_json if isinstance(result.parsed_json, dict) else {}
        raw_candidates = payload.get("candidates", [])
        if not isinstance(raw_candidates, list):
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message="invalid extraction candidates payload",
                details={},
            )
        mapped: list[dict[str, object]] = []
        expected_type = str(getattr(extractor, "candidate_type"))
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            extraction_type = str(item.get("extraction_type", "")).strip()
            if extraction_type and extraction_type != expected_type:
                continue
            body = str(item.get("body", "")).strip()
            quote = str(item.get("evidence_quote", "")).strip()
            if not body and not quote:
                continue
            span_text = quote or body
            start, end, matched_span_text = self._resolve_source_span(
                parsed=parsed,
                primary_query=span_text,
                secondary_query=body if body else quote,
            )
            if start < 0 or end <= start:
                continue
            resolved_text = self._normalize_candidate_text(body or matched_span_text)
            if not resolved_text:
                continue
            mapped.append(
                {
                    "candidate_type": getattr(extractor, "candidate_type"),
                    "text": resolved_text,
                    "source_span": {"start": start, "end": end, "text": matched_span_text},
                    "extractor_name": getattr(extractor, "extractor_name"),
                    "provider_backend": result.provider_backend,
                    "provider_model": result.provider_model,
                    "request_id": result.request_id,
                    "llm_response_id": result.llm_response_id,
                    "usage": result.usage,
                    "fallback_used": result.fallback_used,
                    "degraded": result.degraded,
                    "degraded_reason": result.degraded_reason,
                }
            )
        return mapped, result

    async def _build_document_reading_memo(
        self,
        *,
        request_id: str,
        parsed: ParsedSource,
        failure_mode: str | None,
    ) -> dict[str, object] | None:
        prompt_template = load_prompt_template("document_reader_prompt.txt")
        prompt = render_prompt_template(
            prompt_template,
            {"chunk_text": self._build_prompt_chunk(parsed)},
        )
        backend, model = resolve_research_backend_and_model()
        result = await self._gateway.invoke_text(
            request_id=request_id,
            prompt_name="extraction_document_reader",
            messages=build_messages_from_prompt(prompt),
            backend=backend,
            model=model,
            temperature=0,
            max_tokens=min(
                self._resolve_output_max_tokens(),
                max(_DEFAULT_DOCUMENT_READER_MAX_OUTPUT_TOKENS, 3000),
            ),
            timeout_s=self._resolve_llm_timeout_seconds(),
            allow_fallback=False,
            failure_mode=failure_mode,
        )
        try:
            payload = self._parse_document_memo_payload(result.raw_text)
        except ResearchLLMError:
            retry_prompt = (
                f"{prompt}\n\n"
                "Your previous answer was not valid JSON. Return valid minified JSON only. "
                "Use at most one item in each array. If unsure, use empty arrays."
            )
            result = await self._gateway.invoke_text(
                request_id=request_id,
                prompt_name="extraction_document_reader_retry",
                messages=build_messages_from_prompt(retry_prompt),
                backend=backend,
                model=model,
                temperature=0,
                max_tokens=1800,
                timeout_s=self._resolve_llm_timeout_seconds(),
                allow_fallback=False,
                failure_mode=None,
            )
            payload = self._parse_document_memo_payload(result.raw_text)
        result.parsed_json = payload
        return self._normalize_document_reading_memo(payload) or None

    def _parse_document_memo_payload(self, raw_text: str) -> dict[str, object]:
        normalized = _strip_llm_json_fence(raw_text)
        try:
            parsed = json.loads(normalized)
        except JSONDecodeError as exc:
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message="invalid json from llm",
                details={"json_error": str(exc), "raw_preview": normalized[:200]},
            ) from exc
        if not isinstance(parsed, dict):
            raise ResearchLLMError(
                status_code=502,
                error_code="research.llm_invalid_output",
                message="json output is not an object",
                details={"actual_type": type(parsed).__name__},
            )
        return parsed

    def _normalize_document_reading_memo(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        summary = str(payload.get("document_summary") or "").strip()
        domain_profile = (
            [
                str(item).strip()
                for item in (payload.get("domain_profile") or [])
                if str(item).strip()
            ]
            if isinstance(payload.get("domain_profile"), list)
            else []
        )
        raw_hints = payload.get("structure_hints")
        if not isinstance(raw_hints, dict):
            raw_hints = payload.get("candidate_hints")
        hints = raw_hints if isinstance(raw_hints, dict) else {}
        normalized_hints: dict[str, list[dict[str, str]]] = {}
        for hint_type in (
            "concepts",
            "claims_or_hypotheses",
            "methods_or_measurements",
            "structural_artifacts",
            "results_or_evidence",
            "conditions_or_limits",
            "relation_cues",
            # Backward-compatible keys for older cached or test payloads.
            "evidence",
            "assumption",
            "conflict",
            "failure",
            "validation",
        ):
            raw_items = hints.get(hint_type)
            items: list[dict[str, str]] = []
            if isinstance(raw_items, list):
                for raw_item in raw_items[:4]:
                    if not isinstance(raw_item, dict):
                        continue
                    quote = str(raw_item.get("quote") or "").strip()
                    reason = str(raw_item.get("reason") or "").strip()
                    section = str(raw_item.get("section") or "").strip()
                    if quote:
                        item = {"quote": quote, "reason": reason}
                        if section:
                            item["section"] = section
                        items.append(item)
            normalized_hints[hint_type] = items
        return {
            "document_summary": summary,
            "domain_profile": domain_profile,
            "structure_hints": normalized_hints,
        }

    def _resolve_backend_hint(self) -> str:
        return (
            os.getenv("RESEARCH_LLM_BACKEND")
            or os.getenv("MIRONICKY_LIVE_BACKEND")
            or "unknown"
        )

    def _build_minimal_fallback_candidate(
        self,
        *,
        source: dict[str, object],
        parsed: ParsedSource,
        request_id: str,
        degraded_reason: str | None,
    ) -> dict[str, object]:
        segment, text_override = self._pick_semantic_segment(parsed)
        source_type = str(source.get("source_type") or parsed.source_type)
        candidate_type = {
            "paper": "evidence",
            "note": "assumption",
            "failure_record": "failure",
            "feedback": "evidence",
            "dialogue": "evidence",
        }.get(source_type, "evidence")
        return {
            "candidate_type": candidate_type,
            "text": self._normalize_candidate_text(text_override or segment.text),
            "source_span": {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
            },
            "extractor_name": "deterministic_fallback",
            "provider_backend": self._resolve_backend_hint(),
            "provider_model": "fallback_parser",
            "request_id": request_id,
            "llm_response_id": request_id,
            "usage": _normalized_usage(None),
            "fallback_used": True,
            "degraded": True,
            "degraded_reason": degraded_reason,
        }

    def _build_supplemental_fallback_candidates(
        self,
        *,
        parsed: ParsedSource,
        request_id: str,
        degraded_reason: str | None,
        existing_candidates: list[dict[str, object]],
        minimum_count: int,
    ) -> list[dict[str, object]]:
        if len(existing_candidates) >= minimum_count:
            return []

        used_spans = {
            str((item.get("source_span") or {}).get("text", "")).strip()
            for item in existing_candidates
            if isinstance(item, dict)
        }
        existing_types = {
            str(item.get("candidate_type", "")).strip()
            for item in existing_candidates
            if isinstance(item, dict)
        }
        semantic_segments = [
            segment
            for segment in parsed.segments
            if len(segment.text.strip()) >= 20
        ]
        supplemental: list[dict[str, object]] = []

        def build_candidate(candidate_type: str, segment: object, extractor_name: str) -> dict[str, object]:
            return {
                "candidate_type": candidate_type,
                "text": self._normalize_candidate_text(str(getattr(segment, "text"))),
                "source_span": {
                    "start": int(getattr(segment, "start")),
                    "end": int(getattr(segment, "end")),
                    "text": str(getattr(segment, "text")),
                },
                "extractor_name": extractor_name,
                "provider_backend": self._resolve_backend_hint(),
                "provider_model": "fallback_parser",
                "request_id": request_id,
                "llm_response_id": request_id,
                "usage": _normalized_usage(None),
                "fallback_used": True,
                "degraded": True,
                "degraded_reason": degraded_reason,
            }

        def claim_segment(
            *,
            keywords: tuple[str, ...] = (),
        ):
            lowered_keywords = tuple(keyword.lower() for keyword in keywords)
            for segment in semantic_segments:
                text = str(segment.text).strip()
                if not text or text in used_spans:
                    continue
                lowered = text.lower()
                if lowered_keywords and not any(keyword in lowered for keyword in lowered_keywords):
                    continue
                used_spans.add(text)
                return segment
            return None

        prioritized_types = (
            ("validation", ("楠岃瘉", "鐩戞祴", "璺熻釜", "鎸囨爣", "閫氳繃", "寤鸿")),
            ("failure", ("澶辫触", "椋庨櫓", "浜嬫晠", "鍗辨満", "鑸嗘儏", "娴佸け")),
            ("conflict", ("鍐茬獊", "浜夎", "璐ㄧ枒", "鍙嶅脊", "鐭涚浘")),
            ("evidence", ("鏄剧ず", "鍙戠幇", "鏁版嵁", "琛ㄦ槑", "璇佹槑")),
            ("assumption", ("鍋囪", "棰勬湡", "璁や负", "鎺ㄦ柇", "鍒ゆ柇")),
        )
        # Use stable Unicode escapes to avoid locale-dependent mojibake on Windows shells.
        prioritized_types = (
            (
                "validation",
                (
                    "validation",
                    "verify",
                    "monitor",
                    "metric",
                    "\u9a8c\u8bc1",
                    "\u76d1\u6d4b",
                    "\u8ddf\u8e2a",
                    "\u6307\u6807",
                    "\u901a\u8fc7",
                    "\u5efa\u8bae",
                ),
            ),
            (
                "failure",
                (
                    "failure",
                    "incident",
                    "risk",
                    "\u5931\u8d25",
                    "\u4e8b\u6545",
                    "\u98ce\u9669",
                    "\u5371\u673a",
                    "\u8206\u60c5",
                    "\u6d41\u5931",
                ),
            ),
            (
                "conflict",
                (
                    "conflict",
                    "dispute",
                    "question",
                    "\u51b2\u7a81",
                    "\u4e89\u8bae",
                    "\u8d28\u7591",
                    "\u53cd\u5f39",
                    "\u77db\u76fe",
                ),
            ),
            (
                "evidence",
                (
                    "evidence",
                    "data",
                    "show",
                    "indicate",
                    "\u663e\u793a",
                    "\u53d1\u73b0",
                    "\u6570\u636e",
                    "\u8868\u660e",
                    "\u8bc1\u660e",
                ),
            ),
            (
                "assumption",
                (
                    "assumption",
                    "expectation",
                    "infer",
                    "\u5047\u8bbe",
                    "\u9884\u671f",
                    "\u8ba4\u4e3a",
                    "\u63a8\u65ad",
                    "\u5224\u65ad",
                ),
            ),
        )

        for candidate_type, keywords in prioritized_types:
            if len(existing_candidates) + len(supplemental) >= minimum_count:
                break
            if candidate_type in existing_types:
                continue
            segment = claim_segment(keywords=keywords)
            if segment is None:
                continue
            supplemental.append(
                build_candidate(
                    candidate_type,
                    segment,
                    f"deterministic_supplemental_fallback_{candidate_type}",
                )
            )
            existing_types.add(candidate_type)

        generic_backfill_types = (
            "evidence",
            "assumption",
            "conflict",
            "failure",
            "validation",
        )
        for candidate_type in generic_backfill_types:
            if len(existing_candidates) + len(supplemental) >= minimum_count:
                break
            segment = claim_segment()
            if segment is None:
                break
            supplemental.append(
                build_candidate(
                    candidate_type,
                    segment,
                    f"deterministic_supplemental_fallback_{candidate_type}",
                )
            )

        return supplemental

    def _normalize_candidate_text(self, raw_text: str) -> str:
        normalized = re.sub(r"\s+", " ", str(raw_text or "").strip())
        if not normalized:
            return ""
        if len(normalized) <= _MAX_CANDIDATE_TEXT_CHARS:
            return normalized
        sentence_parts = re.split(r"[。！？!?;；]\s*", normalized)
        first_sentence = next((part.strip() for part in sentence_parts if part.strip()), "")
        if first_sentence:
            normalized = first_sentence
        if len(normalized) > _MAX_CANDIDATE_TEXT_CHARS:
            normalized = normalized[:_MAX_CANDIDATE_TEXT_CHARS].rstrip()
        return normalized

    def _resolve_source_span(
        self,
        *,
        parsed: ParsedSource,
        primary_query: str,
        secondary_query: str | None = None,
    ) -> tuple[int, int, str]:
        normalized_content = parsed.normalized_content
        queries = [str(primary_query or "").strip(), str(secondary_query or "").strip()]
        for query in queries:
            if not query:
                continue
            start = normalized_content.find(query)
            if start >= 0:
                end = start + len(query)
                return start, end, normalized_content[start:end]

        compact_content = self._compact_for_match(normalized_content)
        for query in queries:
            compact_query = self._compact_for_match(query)
            if not compact_query:
                continue
            if compact_query in compact_content:
                for segment in parsed.segments:
                    segment_text = str(segment.text or "")
                    if compact_query in self._compact_for_match(segment_text):
                        return int(segment.start), int(segment.end), segment_text

        loose_content = self._loose_for_match(normalized_content)
        for query in queries:
            loose_query = self._loose_for_match(query)
            if len(loose_query) < 6:
                continue
            if loose_query in loose_content:
                for segment in parsed.segments:
                    segment_text = str(segment.text or "")
                    if loose_query in self._loose_for_match(segment_text):
                        return int(segment.start), int(segment.end), segment_text

        token_query = next((query for query in queries if query), "")
        token_set = self._tokenize_for_match(token_query)
        if token_set:
            best_segment = None
            best_score = 0
            for segment in parsed.segments:
                segment_text = str(segment.text or "").strip()
                if not segment_text:
                    continue
                segment_tokens = self._tokenize_for_match(segment_text)
                overlap = len(token_set.intersection(segment_tokens))
                if overlap <= best_score:
                    continue
                best_score = overlap
                best_segment = segment
            if best_segment is not None and best_score >= 2:
                segment_text = str(best_segment.text or "")
                return int(best_segment.start), int(best_segment.end), segment_text

        return -1, -1, ""

    def _compact_for_match(self, text: str) -> str:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return ""
        return re.sub(r"\s+", " ", lowered)

    def _loose_for_match(self, text: str) -> str:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return ""
        return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", lowered)

    def _tokenize_for_match(self, text: str) -> set[str]:
        tokens = {
            token
            for token in re.findall(r"[0-9a-zA-Z\u4e00-\u9fff]{2,}", self._compact_for_match(text))
            if len(token) >= 2
        }
        for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", self._loose_for_match(text)):
            tokens.update(phrase[index : index + 2] for index in range(len(phrase) - 1))
        return tokens

    def _dedupe_candidates(
        self, raw_candidates: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        deduped: list[dict[str, object]] = []
        seen_keys: set[tuple[str, str, str]] = set()
        for candidate in raw_candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_type = str(candidate.get("candidate_type", "")).strip()
            text = self._normalize_candidate_text(str(candidate.get("text", "")))
            source_span = candidate.get("source_span")
            span_text = (
                str(source_span.get("text", "")).strip()
                if isinstance(source_span, dict)
                else ""
            )
            if not candidate_type or not text:
                continue
            dedupe_key = (
                candidate_type,
                text.lower(),
                self._compact_for_match(span_text),
            )
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            candidate["text"] = text
            deduped.append(candidate)
        return deduped

    def _pick_semantic_segment(self, parsed: ParsedSource):
        for segment in parsed.segments:
            text = segment.text.strip()
            if len(text) < 20:
                continue
            alnum_count = sum(1 for ch in text if ch.isalnum())
            if alnum_count < 8:
                continue
            return segment, None

        # No semantic span is available: keep source span for traceability and use explicit
        # degraded text so downstream does not consume punctuation-only noise as a claim.
        first = parsed.segments[0]
        merged = " ".join(seg.text.strip() for seg in parsed.segments[:4] if seg.text.strip()).strip()
        if len(merged) >= 24 and sum(1 for ch in merged if ch.isalnum()) >= 8:
            end = min(first.start + len(merged), len(parsed.normalized_content))
            return (
                SimpleNamespace(start=first.start, end=end, text=parsed.normalized_content[first.start:end]),
                None,
            )
        return (
            first,
            "auto-degraded candidate: no semantic structured segment extracted; please verify source text manually.",
        )

    def _build_prompt_chunk(self, parsed: ParsedSource) -> str:
        max_chars = _read_positive_int_env(
            "RESEARCH_SOURCE_EXTRACT_MAX_INPUT_CHARS",
            _DEFAULT_EXTRACTION_MAX_INPUT_CHARS,
        )
        max_segments = _read_positive_int_env(
            "RESEARCH_SOURCE_EXTRACT_MAX_INPUT_SEGMENTS",
            _DEFAULT_EXTRACTION_MAX_INPUT_SEGMENTS,
        )
        selected_segments: list[str] = []
        current_length = 0

        for segment in parsed.segments[:max_segments]:
            text = segment.text.strip()
            if not text:
                continue
            separator_length = 1 if selected_segments else 0
            next_length = current_length + separator_length + len(text)
            if selected_segments and next_length > max_chars:
                break
            if not selected_segments and len(text) > max_chars:
                return text[:max_chars].strip()
            selected_segments.append(text)
            current_length = next_length
            if current_length >= max_chars:
                break

        if selected_segments:
            return " ".join(selected_segments)
        return parsed.normalized_content[:max_chars].strip()

    def _resolve_output_max_tokens(self) -> int:
        return _read_positive_int_env(
            "RESEARCH_SOURCE_EXTRACT_MAX_OUTPUT_TOKENS",
            _DEFAULT_EXTRACTION_MAX_OUTPUT_TOKENS,
        )

    def _resolve_llm_timeout_seconds(self) -> float:
        timeout_seconds = _read_positive_int_env(
            "RESEARCH_SOURCE_EXTRACT_LLM_TIMEOUT_SECONDS",
            _DEFAULT_EXTRACTION_LLM_TIMEOUT_SECONDS,
        )
        return float(timeout_seconds)
