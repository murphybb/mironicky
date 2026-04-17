from __future__ import annotations

import os
import re
from dataclasses import asdict
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
from research_layer.services.source_parser import ParseFailureError, ParsedSource, SourceParser

_EXTRACTION_FALLBACK_ALLOWED_ERRORS = {
    "research.llm_failed",
    "research.llm_timeout",
    "research.llm_invalid_output",
}
_DEFAULT_EXTRACTION_MAX_INPUT_CHARS = 120000
_DEFAULT_EXTRACTION_MAX_INPUT_SEGMENTS = 400
_DEFAULT_EXTRACTION_MAX_OUTPUT_TOKENS = 3200
_DEFAULT_EXTRACTION_LLM_TIMEOUT_SECONDS = 20
_MIN_EXTRACTION_CANDIDATE_COUNT = 3
_MIN_EXTRACTION_TYPE_DIVERSITY = 2
_MAX_CANDIDATE_TEXT_CHARS = 220


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
            )
            self._store.update_source_processing(
                source_id=source_id,
                status="parsed",
                normalized_content=parsed.normalized_content,
                last_extract_job_id=job_id,
            )
            raw_candidates: list[dict[str, object]] = []
            latest_trace: LLMCallResult | None = None
            degraded = False
            fallback_used = False
            degraded_reason: str | None = None
            partial_failure_count = 0

            for extractor in self._extractors:
                try:
                    llm_candidates, trace_result = await self._extract_via_llm(
                        extractor=extractor,
                        request_id=request_id,
                        workspace_id=workspace_id,
                        source=source,
                        parsed=parsed,
                        failure_mode=failure_mode,
                    )
                    latest_trace = trace_result
                    raw_candidates.extend(llm_candidates)
                except ResearchLLMError as exc:
                    if allow_fallback and exc.error_code in _EXTRACTION_FALLBACK_ALLOWED_ERRORS:
                        build_fallback = getattr(extractor, "build_fallback_candidates", None)
                        if not callable(build_fallback):
                            build_fallback = getattr(extractor, "extract")
                        fallback_candidates = build_fallback(parsed)
                        fallback_used = True
                        degraded = True
                        degraded_reason = exc.error_code
                        partial_failure_count += 1
                        raw_candidates.extend(
                            [
                                {
                                    "candidate_type": item.candidate_type,
                                    "text": item.text,
                                    "source_span": asdict(item.source_span),
                                    "extractor_name": item.extractor_name,
                                    "provider_backend": latest_trace.provider_backend
                                    if latest_trace
                                    else self._resolve_backend_hint(),
                                    "provider_model": latest_trace.provider_model
                                    if latest_trace
                                    else "fallback_parser",
                                    "request_id": request_id,
                                    "llm_response_id": (
                                        latest_trace.llm_response_id
                                        if latest_trace and latest_trace.llm_response_id
                                        else request_id
                                    ),
                                    "usage": (
                                        _normalized_usage(latest_trace.usage)
                                        if latest_trace
                                        else _normalized_usage(None)
                                    ),
                                    "fallback_used": True,
                                    "degraded": True,
                                    "degraded_reason": degraded_reason,
                                }
                                for item in fallback_candidates
                            ]
                        )
                        continue
                    raise

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
            candidate_type_count = len(
                {
                    str(item.get("candidate_type", "")).strip()
                    for item in raw_candidates
                    if isinstance(item, dict)
                }
            )
            if (
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

        generic_backfill_types = ("evidence", "assumption", "validation", "failure")
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

    def _tokenize_for_match(self, text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[0-9a-zA-Z\u4e00-\u9fff]{2,}", self._compact_for_match(text))
            if len(token) >= 2
        }

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
