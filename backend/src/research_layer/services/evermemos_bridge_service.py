from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from queue import Queue
from threading import Thread
from typing import TypeVar

from agentic_layer.memory_manager import MemoryManager
from api_specs.dtos.memory import RetrieveMemRequest, RetrieveMemResponse
from api_specs.memory_models import MemoryType, RetrieveMethod
from api_specs.memory_types import BaseMemory
from api_specs.request_converter import convert_simple_message_to_memorize_request
from core.observation.logger import get_logger
from research_layer.api.controllers._state_store import ResearchApiStateStore
from service.memory_request_log_service import MemoryRequestLogService

logger = get_logger(__name__)
_T = TypeVar("_T")
_CLAIM_EVENT_PREFIX = "claim::"
_RESEARCH_CLAIM_GROUP_PREFIX = "research_claims::"
_RECALL_MEMORY_TYPES = (
    MemoryType.EPISODIC_MEMORY,
    MemoryType.EVENT_LOG,
    MemoryType.FORESIGHT,
)
_RECALL_METHODS = {
    "keyword": RetrieveMethod.KEYWORD,
    "vector": RetrieveMethod.VECTOR,
    "hybrid": RetrieveMethod.HYBRID,
    "rrf": RetrieveMethod.RRF,
    "agentic": RetrieveMethod.AGENTIC,
}
_RECALL_REQUIRED_ENV_VARS = ("MONGODB_HOST", "ES_HOSTS", "MILVUS_HOST")
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on", "enabled"}
_FALSEY_ENV_VALUES = {"0", "false", "no", "off", "disabled"}


def _build_research_claim_group_id(workspace_id: str) -> str:
    return f"{_RESEARCH_CLAIM_GROUP_PREFIX}{workspace_id}"


class _AsyncMemoryRuntimeMixin:
    def _get_memory_manager(self) -> MemoryManager:
        return MemoryManager()

    def _run_awaitable_blocking(
        self, factory: Callable[[], Awaitable[_T]]
    ) -> _T:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None or not loop.is_running():
            return asyncio.run(factory())

        queue: Queue[tuple[str, object]] = Queue(maxsize=1)

        def _runner() -> None:
            thread_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(thread_loop)
                result = thread_loop.run_until_complete(factory())
                queue.put(("result", result))
            except Exception as exc:  # pragma: no cover - exercised via failure paths
                queue.put(("error", exc))
            finally:
                try:
                    thread_loop.run_until_complete(thread_loop.shutdown_asyncgens())
                except Exception:
                    pass
                asyncio.set_event_loop(None)
                thread_loop.close()

        thread = Thread(
            target=_runner,
            name="research-memory-runtime",
            daemon=True,
        )
        thread.start()
        thread.join()
        kind, payload = queue.get()
        if kind == "error":
            raise payload  # type: ignore[misc]
        return payload  # type: ignore[return-value]


class ResearchMemoryBridge(_AsyncMemoryRuntimeMixin):
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def sync_claim(
        self,
        *,
        claim: dict[str, object],
        request_id: str,
    ) -> dict[str, object]:
        claim_id = str(claim["claim_id"])
        workspace_id = str(claim["workspace_id"])
        sync_mode = "pending"
        self._store.upsert_claim_memory_link(
            claim_id=claim_id,
            workspace_id=workspace_id,
            memory_id=None,
            sync_mode=sync_mode,
            status="pending",
            reason=None,
        )
        self._store.emit_event(
            event_name="claim_memory_bridge_started",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            source_id=str(claim["source_id"]),
            component="evermemos_bridge_service",
            step="memory_bridge",
            status="started",
            refs={"claim_id": claim_id, "sync_mode": sync_mode},
        )

        endpoint = os.getenv("RESEARCH_EVERMEMOS_BRIDGE_URL", "").strip()
        if not endpoint:
            return self._sync_to_local_memory(claim=claim, request_id=request_id)

        try:
            response = self._sync_over_http(
                endpoint=endpoint,
                claim=claim,
                request_id=request_id,
            )
            memory_id = str(response.get("memory_id") or "").strip()
            if not memory_id:
                raise ValueError("bridge response missing memory_id")
            return self._finalize_link(
                claim=claim,
                request_id=request_id,
                memory_id=memory_id,
                sync_mode="http",
                status="synced",
                reason=None,
                last_error=None,
            )
        except Exception as exc:
            logger.warning(
                "research.claim_memory_bridge.failed request_id=%s claim_id=%s reason=%s",
                request_id,
                claim_id,
                str(exc),
            )
            return self._finalize_link(
                claim=claim,
                request_id=request_id,
                memory_id=None,
                sync_mode="http",
                status="failed",
                reason=self._normalize_reason(str(exc)),
                last_error={"message": str(exc)},
            )

    def _sync_to_local_memory(
        self,
        *,
        claim: dict[str, object],
        request_id: str,
    ) -> dict[str, object]:
        try:
            message_payload = self._build_local_message_payload(claim)
            memorize_request = self._run_awaitable_blocking(
                lambda: convert_simple_message_to_memorize_request(message_payload)
            )
            message_ids = self._run_awaitable_blocking(
                lambda: self._get_memory_request_log_service().save_request_logs(
                    request=memorize_request,
                    version="research-p0b",
                    endpoint_name="research_claim_bridge",
                    method="LOCAL",
                    url="research://claim-memory-bridge",
                    raw_input_dict=message_payload,
                )
            )
            memorize_count = self._run_awaitable_blocking(
                lambda: self._get_memory_manager().memorize(memorize_request)
            )
            message_log_ref = self._build_message_log_ref(message_ids)
            if int(memorize_count) > 0:
                return self._finalize_link(
                    claim=claim,
                    request_id=request_id,
                    memory_id=None,
                    sync_mode="local_memory_manager",
                    status="written_unaddressable",
                    reason="addressable_memory_id_unavailable",
                    last_error=None,
                    extra_refs={"message_log_ref": message_log_ref},
                )
            return self._finalize_link(
                claim=claim,
                request_id=request_id,
                memory_id=None,
                sync_mode="local_memory_manager",
                status="logged_only",
                reason="memorize_returned_zero",
                last_error=None,
                extra_refs={"message_log_ref": message_log_ref},
            )
        except Exception as exc:
            logger.warning(
                "research.claim_memory_bridge.local_failed request_id=%s claim_id=%s reason=%s",
                request_id,
                str(claim.get("claim_id") or ""),
                str(exc),
            )
            return self._finalize_link(
                claim=claim,
                request_id=request_id,
                memory_id=None,
                sync_mode="local_memory_manager",
                status="failed",
                reason=self._normalize_reason(str(exc)),
                last_error={"message": str(exc)},
            )

    def _sync_over_http(
        self,
        *,
        endpoint: str,
        claim: dict[str, object],
        request_id: str,
    ) -> dict[str, object]:
        payload = json.dumps(self._build_claim_payload(claim)).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Request-Id": request_id,
        }
        token = os.getenv("RESEARCH_EVERMEMOS_BRIDGE_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers=headers,
            method="POST",
        )
        timeout_s = float(os.getenv("RESEARCH_EVERMEMOS_BRIDGE_TIMEOUT_S", "5") or "5")
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                status_code = getattr(response, "status", None) or response.getcode()
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"http_{int(exc.code)}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"transport_error:{exc.reason}") from exc

        if int(status_code) >= 400:
            raise RuntimeError(f"http_{int(status_code)}")
        if not body:
            return {}
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("invalid_json_response") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid_bridge_response")
        return decoded

    def _build_local_message_payload(
        self, claim: dict[str, object]
    ) -> dict[str, object]:
        claim_id = str(claim["claim_id"])
        workspace_id = str(claim["workspace_id"])
        created_at = claim.get("updated_at") or claim.get("created_at")
        if isinstance(created_at, datetime):
            created_at_iso = created_at.astimezone(timezone.utc).isoformat()
        else:
            created_at_iso = datetime.now(timezone.utc).isoformat()
        return {
            "group_id": _build_research_claim_group_id(workspace_id),
            "group_name": f"Research Claims {workspace_id}",
            "message_id": f"{_CLAIM_EVENT_PREFIX}{claim_id}",
            "create_time": created_at_iso,
            "sender": "research_layer_claim_bridge",
            "sender_name": "research_layer_claim_bridge",
            "role": "assistant",
            "content": str(claim.get("text") or "").strip(),
        }

    def _build_claim_payload(self, claim: dict[str, object]) -> dict[str, object]:
        return {
            "claim_id": claim["claim_id"],
            "workspace_id": claim["workspace_id"],
            "source_id": claim["source_id"],
            "candidate_id": claim["candidate_id"],
            "claim_type": claim["claim_type"],
            "semantic_type": claim.get("semantic_type"),
            "text": claim["text"],
            "normalized_text": claim["normalized_text"],
            "quote": claim.get("quote"),
            "source_span": claim.get("source_span", {}),
            "trace_refs": claim.get("trace_refs", {}),
        }

    def _get_memory_request_log_service(self) -> MemoryRequestLogService:
        return MemoryRequestLogService()

    def _build_message_log_ref(self, message_ids: list[str]) -> str | None:
        if not message_ids:
            return None
        message_id = str(message_ids[0]).strip()
        if not message_id:
            return None
        return f"message_log:{message_id}"

    def _finalize_link(
        self,
        *,
        claim: dict[str, object],
        request_id: str,
        memory_id: str | None,
        sync_mode: str,
        status: str,
        reason: str | None,
        last_error: dict[str, object] | None,
        extra_refs: dict[str, object] | None = None,
    ) -> dict[str, object]:
        link = self._store.upsert_claim_memory_link(
            claim_id=str(claim["claim_id"]),
            workspace_id=str(claim["workspace_id"]),
            memory_id=memory_id,
            sync_mode=sync_mode,
            status=status,
            reason=reason,
            last_error=last_error,
        )
        self._store.emit_event(
            event_name="claim_memory_bridge_completed",
            request_id=request_id,
            job_id=None,
            workspace_id=str(claim["workspace_id"]),
            source_id=str(claim["source_id"]),
            component="evermemos_bridge_service",
            step="memory_bridge",
            status=status,
            refs={
                "claim_id": claim["claim_id"],
                "memory_id": memory_id,
                "sync_mode": sync_mode,
                "reason": reason,
                **(extra_refs or {}),
            },
            error=last_error,
        )
        return link

    def _normalize_reason(self, reason: str) -> str:
        normalized = str(reason or "").strip()
        return normalized[:256] if normalized else "unknown_bridge_error"


class ResearchMemoryRecallService(_AsyncMemoryRuntimeMixin):
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def recall(
        self,
        *,
        workspace_id: str,
        query_text: str,
        requested_method: str,
        scope_claim_ids: list[str] | None = None,
        scope_mode: str = "prefer",
        top_k: int = 8,
        request_id: str | None = None,
        trace_refs: dict[str, object] | None = None,
    ) -> dict[str, object]:
        normalized_claim_ids = self._normalize_claim_ids(scope_claim_ids or [])
        normalized_query = " ".join(str(query_text or "").split())
        if scope_mode == "require" and not normalized_claim_ids:
            return self.failed(
                workspace_id=workspace_id,
                requested_method=requested_method,
                reason="required_claim_scope_missing",
                query_text=normalized_query,
                request_id=request_id,
                trace_refs=trace_refs,
            )
        if not normalized_query:
            return self.skipped(
                workspace_id=workspace_id,
                requested_method=requested_method,
                reason="missing_query_text",
                query_text="",
                request_id=request_id,
                trace_refs=trace_refs,
            )
        return self.recall_for_claims(
            workspace_id=workspace_id,
            claim_ids=normalized_claim_ids,
            query_text=normalized_query,
            requested_method=requested_method,
            top_k=top_k,
            request_id=request_id or f"recall::{workspace_id}::{scope_mode}",
            context_type=str(trace_refs.get("context_type")) if isinstance(trace_refs, dict) and trace_refs.get("context_type") else "main_path",
            context_ref=trace_refs,
            scope_mode=scope_mode,
        )

    def skipped(
        self,
        *,
        workspace_id: str,
        requested_method: str,
        reason: str,
        query_text: str | None = None,
        request_id: str | None = None,
        trace_refs: dict[str, object] | None = None,
    ) -> dict[str, object]:
        applied_method, fallback_reason = self._resolve_method(requested_method)
        return self.build_skipped_response(
            requested_method=str(requested_method or "hybrid").strip().lower() or "hybrid",
            applied_method=applied_method.value,
            reason=reason if fallback_reason is None else f"{reason}; {fallback_reason}",
            query_text=str(query_text or ""),
            workspace_id=workspace_id,
            claim_ids=[],
            context_type="main_path",
            request_id=request_id,
            context_ref=trace_refs,
        )

    def failed(
        self,
        *,
        workspace_id: str,
        requested_method: str,
        reason: str,
        query_text: str | None = None,
        request_id: str | None = None,
        trace_refs: dict[str, object] | None = None,
    ) -> dict[str, object]:
        applied_method, fallback_reason = self._resolve_method(requested_method)
        response = self._build_response(
            status="failed",
            requested_method=str(requested_method or "hybrid").strip().lower() or "hybrid",
            applied_method=applied_method.value,
            reason=reason if fallback_reason is None else f"{reason}; {fallback_reason}",
            query_text=str(query_text or ""),
            items=[],
            workspace_id=workspace_id,
            claim_ids=[],
            context_type="main_path",
            context_ref=trace_refs,
            per_type_count={},
        )
        self._emit_recall_completed_event(
            request_id=request_id or f"recall::{workspace_id}::failed",
            workspace_id=workspace_id,
            status="failed",
            requested_method=response["requested_method"],
            applied_method=response["applied_method"],
            claim_ids=[],
            reason=response["reason"],
            context_type="main_path",
            context_ref=trace_refs,
            query_text=str(query_text or ""),
            returned_count=response["total"],
            candidate_count=0,
            error=None,
        )
        return response

    def recall_for_claims(
        self,
        *,
        workspace_id: str,
        claim_ids: list[str],
        query_text: str,
        requested_method: str,
        top_k: int,
        request_id: str,
        context_type: str,
        context_ref: dict[str, object] | None = None,
        scope_mode: str = "require",
    ) -> dict[str, object]:
        normalized_claim_ids = self._normalize_claim_ids(claim_ids)
        requested = str(requested_method or "hybrid").strip().lower() or "hybrid"
        applied_method, reason = self._resolve_method(requested)
        query = self._resolve_query_text(
            workspace_id=workspace_id,
            query_text=query_text,
            claim_ids=normalized_claim_ids,
        )
        safe_top_k = min(max(int(top_k or 1), 1), 25)
        if not query:
            return self.build_skipped_response(
                requested_method=requested,
                applied_method=applied_method.value,
                reason="missing_query_and_claim_scope",
                query_text="",
                workspace_id=workspace_id,
                claim_ids=normalized_claim_ids,
                context_type=context_type,
                request_id=request_id,
                context_ref=context_ref,
            )
        skip_reason = self._recall_skip_reason()
        if skip_reason is not None:
            return self.build_skipped_response(
                requested_method=requested,
                applied_method=applied_method.value,
                reason=skip_reason if reason is None else f"{skip_reason}; {reason}",
                query_text=query,
                workspace_id=workspace_id,
                claim_ids=normalized_claim_ids,
                context_type=context_type,
                request_id=request_id,
                context_ref=context_ref,
            )

        group_id = _build_research_claim_group_id(workspace_id)
        self._store.emit_event(
            event_name="evermemos_recall_started",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="evermemos_bridge_service",
            step="memory_recall",
            status="started",
            refs={
                "context_type": context_type,
                "context_ref": context_ref or {},
                "requested_method": requested,
                "applied_method": applied_method.value,
                "claim_ids": normalized_claim_ids,
            },
            metrics={"query_length": len(query), "top_k": safe_top_k},
        )
        try:
            flattened: list[dict[str, object]] = []
            per_type_count: dict[str, int] = {}
            for memory_type in _RECALL_MEMORY_TYPES:
                response = self._run_awaitable_blocking(
                    lambda memory_type=memory_type: self._get_memory_manager().retrieve_mem(
                        RetrieveMemRequest(
                            group_id=group_id,
                            memory_types=[memory_type],
                            top_k=safe_top_k,
                            include_metadata=True,
                            query=query,
                            retrieve_method=applied_method,
                        )
                    )
                )
                items = self._flatten_retrieve_response(
                    response=response,
                    fallback_memory_type=memory_type.value,
                )
                per_type_count[memory_type.value] = len(items)
                flattened.extend(items)
            scoped = self._scope_items(
                flattened,
                normalized_claim_ids,
                scope_mode=scope_mode,
            )
            deduped = self._dedupe_items(scoped)
            limited = deduped[:safe_top_k]
            status = "completed" if limited else "empty"
            response = self._build_response(
                status=status,
                requested_method=requested,
                applied_method=applied_method.value,
                reason=reason,
                query_text=query,
                items=limited,
                workspace_id=workspace_id,
                claim_ids=normalized_claim_ids,
                context_type=context_type,
                context_ref=context_ref,
                per_type_count=per_type_count,
            )
            self._emit_recall_completed_event(
                request_id=request_id,
                workspace_id=workspace_id,
                status=status,
                requested_method=requested,
                applied_method=applied_method.value,
                claim_ids=normalized_claim_ids,
                reason=response["reason"],
                context_type=context_type,
                context_ref=context_ref,
                query_text=query,
                returned_count=response["total"],
                candidate_count=len(flattened),
                error=None,
            )
            return response
        except Exception as exc:
            normalized_reason = self._normalize_reason(str(exc))
            self._emit_recall_completed_event(
                request_id=request_id,
                workspace_id=workspace_id,
                status="failed",
                requested_method=requested,
                applied_method=applied_method.value,
                claim_ids=normalized_claim_ids,
                reason=normalized_reason,
                context_type=context_type,
                context_ref=context_ref,
                query_text=query,
                returned_count=0,
                candidate_count=0,
                error={"message": str(exc)},
            )
            return self._build_response(
                status="failed",
                requested_method=requested,
                applied_method=applied_method.value,
                reason=normalized_reason,
                query_text=query,
                items=[],
                workspace_id=workspace_id,
                claim_ids=normalized_claim_ids,
                context_type=context_type,
                context_ref=context_ref,
                per_type_count={},
            )

    def build_skipped_response(
        self,
        *,
        requested_method: str,
        applied_method: str,
        reason: str,
        query_text: str,
        workspace_id: str,
        claim_ids: list[str],
        context_type: str,
        request_id: str | None = None,
        context_ref: dict[str, object] | None = None,
    ) -> dict[str, object]:
        response = self._build_response(
            status="skipped",
            requested_method=requested_method,
            applied_method=applied_method,
            reason=reason,
            query_text=query_text,
            items=[],
            workspace_id=workspace_id,
            claim_ids=self._normalize_claim_ids(claim_ids),
            context_type=context_type,
            context_ref=context_ref,
            per_type_count={},
        )
        self._emit_recall_completed_event(
            request_id=request_id or f"recall::{workspace_id}::skipped",
            workspace_id=workspace_id,
            status="skipped",
            requested_method=requested_method,
            applied_method=applied_method,
            claim_ids=self._normalize_claim_ids(claim_ids),
            reason=reason,
            context_type=context_type,
            context_ref=context_ref,
            query_text=query_text,
            returned_count=0,
            candidate_count=0,
            error=None,
        )
        return response

    def _emit_recall_completed_event(
        self,
        *,
        request_id: str,
        workspace_id: str,
        status: str,
        requested_method: str,
        applied_method: str,
        claim_ids: list[str],
        reason: str | None,
        context_type: str,
        context_ref: dict[str, object] | None,
        query_text: str,
        returned_count: int,
        candidate_count: int,
        error: dict[str, object] | None,
    ) -> None:
        self._store.emit_event(
            event_name="evermemos_recall_completed",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="evermemos_bridge_service",
            step="memory_recall",
            status=status,
            refs={
                "context_type": context_type,
                "context_ref": context_ref or {},
                "requested_method": requested_method,
                "applied_method": applied_method,
                "claim_ids": claim_ids,
                "reason": reason,
            },
            metrics={
                "query_length": len(query_text),
                "returned_count": returned_count,
                "candidate_count": candidate_count,
            },
            error=error,
        )

    def _resolve_method(self, requested_method: str) -> tuple[RetrieveMethod, str | None]:
        normalized = str(requested_method or "").strip().lower()
        if normalized == "logical":
            return RetrieveMethod.HYBRID, "logical_not_supported_by_evermemos"
        resolved = _RECALL_METHODS.get(normalized)
        if resolved is None:
            return RetrieveMethod.HYBRID, "unsupported_recall_method_defaulted_to_hybrid"
        return resolved, None

    def _recall_skip_reason(self) -> str | None:
        disabled = os.getenv("RESEARCH_EVERMEMOS_RECALL_DISABLED", "").strip().lower()
        if disabled in _TRUTHY_ENV_VALUES:
            return "evermemos_recall_disabled"

        enabled = os.getenv("RESEARCH_EVERMEMOS_RECALL_ENABLED")
        if enabled is not None and enabled.strip().lower() in _FALSEY_ENV_VALUES:
            return "evermemos_recall_disabled"

        if not self._uses_default_memory_manager():
            return None
        if any(not os.getenv(name, "").strip() for name in _RECALL_REQUIRED_ENV_VARS):
            return "evermemos_recall_unconfigured"
        return None

    def _uses_default_memory_manager(self) -> bool:
        return (
            getattr(self._get_memory_manager, "__func__", None)
            is _AsyncMemoryRuntimeMixin._get_memory_manager
        )

    def _resolve_query_text(
        self,
        *,
        workspace_id: str,
        query_text: str,
        claim_ids: list[str],
    ) -> str:
        normalized_query = " ".join(str(query_text or "").split())
        if normalized_query:
            return normalized_query
        claim_texts: list[str] = []
        for claim_id in claim_ids:
            claim = self._store.get_claim(claim_id)
            if claim is None:
                continue
            text = " ".join(str(claim.get("text") or "").split())
            if text:
                claim_texts.append(text)
            if len(claim_texts) >= 3:
                break
        return " ".join(claim_texts)

    def _normalize_claim_ids(self, claim_ids: list[str]) -> list[str]:
        return sorted({str(claim_id).strip() for claim_id in claim_ids if str(claim_id).strip()})

    def _flatten_retrieve_response(
        self,
        *,
        response: RetrieveMemResponse,
        fallback_memory_type: str,
    ) -> list[dict[str, object]]:
        flattened: list[dict[str, object]] = []
        memories = list(response.memories or [])
        score_maps = list(response.scores or [])
        for index, memory_group in enumerate(memories):
            if not isinstance(memory_group, dict):
                continue
            score_group = score_maps[index] if index < len(score_maps) else {}
            score_group_dict = score_group if isinstance(score_group, dict) else {}
            for group_id, raw_memories in memory_group.items():
                memory_list = raw_memories if isinstance(raw_memories, list) else []
                raw_scores = score_group_dict.get(group_id, [])
                score_list = raw_scores if isinstance(raw_scores, list) else []
                for memory_index, memory in enumerate(memory_list):
                    memory_dict = self._memory_to_dict(memory)
                    linked_claim_ids = self._extract_claim_ids(
                        memory_dict.get("ori_event_id_list")
                    )
                    flattened.append(
                        {
                            "memory_type": str(
                                memory_dict.get("memory_type") or fallback_memory_type
                            ),
                            "memory_id": str(memory_dict.get("id") or ""),
                            "score": float(
                                score_list[memory_index]
                                if memory_index < len(score_list)
                                else 0.0
                            ),
                            "title": self._memory_title(memory_dict),
                            "snippet": self._memory_snippet(memory_dict),
                            "timestamp": self._memory_timestamp(memory_dict),
                            "linked_claim_ids": linked_claim_ids,
                            "trace_refs": {
                                "group_id": str(group_id),
                                "ori_event_id_list": memory_dict.get(
                                    "ori_event_id_list", []
                                ),
                                "parent_id": memory_dict.get("parent_id"),
                                "parent_type": memory_dict.get("parent_type"),
                            },
                        }
                    )
        return flattened

    def _memory_to_dict(self, memory: BaseMemory | dict[str, object] | object) -> dict[str, object]:
        if isinstance(memory, dict):
            return dict(memory)
        to_dict = getattr(memory, "to_dict", None)
        if callable(to_dict):
            data = to_dict()
            if isinstance(data, dict):
                return data
        if hasattr(memory, "__dict__"):
            return {
                key: value
                for key, value in vars(memory).items()
                if not key.startswith("_")
            }
        return {}

    def _extract_claim_ids(self, ori_event_id_list: object) -> list[str]:
        if not isinstance(ori_event_id_list, list):
            return []
        claim_ids = []
        for raw_event_id in ori_event_id_list:
            event_id = str(raw_event_id or "").strip()
            if not event_id.startswith(_CLAIM_EVENT_PREFIX):
                continue
            claim_id = event_id.removeprefix(_CLAIM_EVENT_PREFIX).strip()
            if claim_id:
                claim_ids.append(claim_id)
        return sorted(set(claim_ids))

    def _memory_title(self, memory: dict[str, object]) -> str:
        for key in ("summary", "subject", "foresight", "atomic_fact", "episode"):
            value = self._coerce_text(memory.get(key))
            if value:
                return value[:160]
        return "EverMemOS recall"

    def _memory_snippet(self, memory: dict[str, object]) -> str:
        for key in ("episode", "atomic_fact", "evidence", "foresight", "summary"):
            value = self._coerce_text(memory.get(key))
            if value:
                return value[:320]
        return self._memory_title(memory)

    def _memory_timestamp(self, memory: dict[str, object]) -> str | None:
        value = memory.get("timestamp") or memory.get("time")
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _coerce_text(self, value: object) -> str:
        if isinstance(value, list):
            normalized = [str(item).strip() for item in value if str(item).strip()]
            return " ".join(normalized)
        text = str(value or "").strip()
        return text

    def _scope_items(
        self,
        items: list[dict[str, object]],
        claim_ids: list[str],
        *,
        scope_mode: str,
    ) -> list[dict[str, object]]:
        if not claim_ids:
            return items
        claim_scope = set(claim_ids)
        normalized_mode = str(scope_mode or "require").strip().lower()
        if normalized_mode == "require":
            return [
                item
                for item in items
                if claim_scope & set(item.get("linked_claim_ids", []))
            ]
        if normalized_mode != "prefer":
            return items
        preferred: list[dict[str, object]] = []
        fallback: list[dict[str, object]] = []
        for item in items:
            if claim_scope & set(item.get("linked_claim_ids", [])):
                preferred.append(
                    {
                        **item,
                        "score": float(item.get("score") or 0.0) + 1.0,
                    }
                )
            else:
                fallback.append(item)
        return preferred + fallback

    def _dedupe_items(self, items: list[dict[str, object]]) -> list[dict[str, object]]:
        deduped: dict[tuple[str, str], dict[str, object]] = {}
        for item in items:
            memory_type = str(item.get("memory_type") or "")
            memory_id = str(item.get("memory_id") or "")
            fallback_key = "|".join(item.get("linked_claim_ids", []))
            key = (memory_type, memory_id or fallback_key)
            existing = deduped.get(key)
            if existing is None or float(item.get("score") or 0.0) > float(
                existing.get("score") or 0.0
            ):
                deduped[key] = item
        return sorted(
            deduped.values(),
            key=lambda item: (
                -float(item.get("score") or 0.0),
                str(item.get("memory_type") or ""),
                str(item.get("memory_id") or ""),
            ),
        )

    def _build_response(
        self,
        *,
        status: str,
        requested_method: str,
        applied_method: str,
        reason: str | None,
        query_text: str,
        items: list[dict[str, object]],
        workspace_id: str,
        claim_ids: list[str],
        context_type: str,
        context_ref: dict[str, object] | None,
        per_type_count: dict[str, int],
    ) -> dict[str, object]:
        response_items = [
            {
                "memory_type": str(item.get("memory_type") or ""),
                "memory_id": str(item.get("memory_id") or ""),
                "score": float(item.get("score") or 0.0),
                "title": str(item.get("title") or ""),
                "snippet": str(item.get("snippet") or ""),
                "timestamp": item.get("timestamp"),
                "linked_claim_refs": [
                    {"claim_id": claim_id}
                    for claim_id in item.get("linked_claim_ids", [])
                ],
                "trace_refs": item.get("trace_refs", {}),
            }
            for item in items
        ]
        return {
            "status": status,
            "requested_method": requested_method,
            "applied_method": applied_method,
            "reason": reason,
            "query_text": query_text,
            "total": len(response_items),
            "items": response_items,
            "trace_refs": {
                "workspace_id": workspace_id,
                "group_id": _build_research_claim_group_id(workspace_id),
                "claim_ids": claim_ids,
                "context_type": context_type,
                "context_ref": context_ref or {},
                "memory_types": [memory_type.value for memory_type in _RECALL_MEMORY_TYPES],
                "per_type_count": per_type_count,
            },
        }

    def _normalize_reason(self, reason: str) -> str:
        normalized = str(reason or "").strip()
        return normalized[:256] if normalized else "unknown_recall_error"


EverMemOSBridgeService = ResearchMemoryBridge
EverMemOSRecallService = ResearchMemoryRecallService
