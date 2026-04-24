from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.evermemos_bridge_service import EverMemOSRecallService


class SourceMemoryRecallService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._memory_recall_service = EverMemOSRecallService(store)

    def recall_for_source(
        self,
        *,
        workspace_id: str,
        source_id: str,
        query_text: str,
        request_id: str,
        requested_method: str = "logical",
        trace_refs: dict[str, object] | None = None,
    ) -> dict[str, object]:
        source_trace_refs = {
            "source_id": source_id,
            "request_id": request_id,
            **(trace_refs or {}),
        }
        try:
            response = self._memory_recall_service.recall(
                workspace_id=workspace_id,
                query_text=query_text,
                requested_method=requested_method,
                scope_claim_ids=[],
                scope_mode="prefer",
                request_id=request_id,
                trace_refs={
                    "context_type": "source_import",
                    **source_trace_refs,
                },
            )
        except Exception as exc:
            error = {
                "type": type(exc).__name__,
                "message": str(exc),
                "reason": self._normalize_reason(str(exc)),
            }
            response = {
                "status": "failed",
                "reason": error["reason"],
                "requested_method": requested_method,
                "applied_method": None,
                "query_text": self._normalize_query_text(query_text),
                "total": 0,
                "items": [],
                "trace_refs": source_trace_refs,
                "error": error,
            }

        items = response.get("items")
        normalized_items = items if isinstance(items, list) else []
        trace = response.get("trace_refs")
        normalized_trace = trace if isinstance(trace, dict) else {}
        total = response.get("total")
        persisted_query_text = self._normalize_query_text(
            response.get("query_text")
            if response.get("query_text") is not None
            else query_text
        )
        error = (
            response.get("error") if isinstance(response.get("error"), dict) else None
        )
        if error is None and str(response.get("status") or "").strip() == "failed":
            reason = (
                str(response.get("reason")).strip()
                if response.get("reason") is not None
                else "source_memory_recall_failed"
            )
            error = {"message": reason, "reason": self._normalize_reason(reason)}
        result = self._store.create_source_memory_recall_result(
            workspace_id=workspace_id,
            source_id=source_id,
            status=str(response.get("status") or "failed"),
            reason=(
                str(response.get("reason")).strip()
                if response.get("reason") is not None
                else None
            ),
            requested_method=str(response.get("requested_method") or requested_method),
            applied_method=(
                str(response.get("applied_method")).strip()
                if response.get("applied_method") is not None
                else None
            ),
            query_text=persisted_query_text,
            total=int(total) if isinstance(total, int) else len(normalized_items),
            items=[item for item in normalized_items if isinstance(item, dict)],
            trace_refs=normalized_trace,
            error=error,
            request_id=request_id,
        )
        self._store.emit_event(
            event_name="source_memory_recall_recorded",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            source_id=source_id,
            component="source_memory_recall_service",
            step="memory_recall",
            status=str(result["status"]),
            refs={
                "recall_id": result["recall_id"],
                "requested_method": result["requested_method"],
                "applied_method": result["applied_method"],
                "reason": result["reason"],
            },
            metrics={"total": result["total"]},
        )
        return result

    def _normalize_reason(self, reason: str) -> str:
        normalized = str(reason or "").strip()
        return normalized[:256] if normalized else "unknown_source_recall_error"

    def _normalize_query_text(self, query_text: object) -> str:
        return " ".join(str(query_text or "").split())
