from __future__ import annotations

from dataclasses import dataclass

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.api.schemas.memory import (
    validate_memory_view_type,
    validate_retrieve_method,
)
from research_layer.api.schemas.retrieval import RETRIEVAL_VIEW_VALUES
from research_layer.services.hypothesis_service import (
    HypothesisService,
    HypothesisServiceError,
)
from research_layer.services.retrieval_views_service import (
    ResearchRetrievalService,
    RetrievalServiceError,
)
from research_layer.services.tool_capability_graph_service import (
    ToolCapabilityGraphService,
)


@dataclass(slots=True)
class MemoryVaultServiceError(Exception):
    status_code: int
    error_code: str
    message: str
    details: dict[str, object]

    def __str__(self) -> str:
        return self.message


class MemoryVaultService:
    _ACTION_SEMANTICS = {
        "open_in_workbench": "navigation_only",
        "bind_to_current_route": "backend_controlled_action",
        "memory_to_hypothesis_candidate": "backend_controlled_action",
    }

    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._retrieval_service = ResearchRetrievalService(store)
        self._hypothesis_service = HypothesisService(store)
        self._tool_capability_graph = ToolCapabilityGraphService()

    def _raise(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        raise MemoryVaultServiceError(
            status_code=status_code,
            error_code=error_code,
            message=message,
            details=details or {},
        )

    def list_memory(
        self,
        *,
        workspace_id: str,
        view_types: list[str],
        query: str,
        retrieve_method: str,
        top_k_per_view: int,
        metadata_filters_by_view: dict[str, dict[str, object]],
        request_id: str,
    ) -> dict[str, object]:
        if not view_types:
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="view_types must not be empty",
            )
        normalized_method = self._validate_retrieve_method(retrieve_method)
        normalized_views = self._normalize_view_types(view_types)
        normalized_filters = self._normalize_filters(
            view_types=normalized_views,
            metadata_filters_by_view=metadata_filters_by_view,
        )
        tool_capability_refs = self._tool_capability_graph.plan_for_memory(
            view_types=normalized_views,
            retrieve_method=normalized_method,
        )

        items: list[dict[str, object]] = []
        for view_type in normalized_views:
            filters = normalized_filters.get(view_type, {})
            try:
                result = self._retrieval_service.retrieve(
                    workspace_id=workspace_id,
                    view_type=view_type,
                    query=query,
                    retrieve_method=normalized_method,
                    top_k=top_k_per_view,
                    metadata_filters=filters,
                    request_id=request_id,
                )
            except RetrievalServiceError as exc:
                self._raise(
                    status_code=exc.status_code,
                    error_code=exc.error_code,
                    message=exc.message,
                    details=exc.details,
                )
            for item in result["items"]:
                items.append(
                    {
                        "read_model_kind": "retrieval_backed",
                        "memory_id": item["result_id"],
                        "memory_view_type": view_type,
                        "score": item["score"],
                        "title": item["title"],
                        "snippet": item["snippet"],
                        "source_ref": item["source_ref"],
                        "graph_refs": item["graph_refs"],
                        "formal_refs": item["formal_refs"],
                        "supporting_refs": item["supporting_refs"],
                        "trace_refs": item["trace_refs"],
                        "retrieval_context": {
                            "view_type": view_type,
                            "retrieve_method": normalized_method,
                            "query_ref": result["query_ref"],
                            "metadata_filter_refs": result["metadata_filter_refs"],
                        },
                    }
                )
        items.sort(key=lambda item: (-float(item["score"]), str(item["memory_id"])))
        return {
            "read_model_kind": "retrieval_backed_read_model",
            "workspace_id": workspace_id,
            "controlled_action_semantics": dict(self._ACTION_SEMANTICS),
            "tool_capability_refs": tool_capability_refs,
            "total": len(items),
            "items": items,
        }

    def bind_to_current_route(
        self,
        *,
        workspace_id: str,
        route_id: str,
        memory_id: str,
        memory_view_type: str,
        note: str | None,
        request_id: str,
    ) -> dict[str, object]:
        view_type = self._validate_view_type(memory_view_type)
        route = self._store.get_route(route_id)
        if route is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message="route not found",
                details={"route_id": route_id},
            )
        if str(route["workspace_id"]) != workspace_id:
            self._raise(
                status_code=409,
                error_code="research.conflict",
                message="workspace_id does not match route ownership",
                details={"route_id": route_id},
            )

        memory_item = self._resolve_memory_item(
            workspace_id=workspace_id,
            view_type=view_type,
            memory_id=memory_id,
        )
        duplicate = self._store.find_memory_action(
            workspace_id=workspace_id,
            action_type="bind_to_current_route",
            memory_view_type=view_type,
            memory_result_id=memory_id,
            route_id=route_id,
        )
        if duplicate is not None:
            self._raise(
                status_code=409,
                error_code="research.invalid_state",
                message="memory is already bound to this route",
                details={
                    "route_id": route_id,
                    "memory_id": memory_id,
                    "memory_view_type": view_type,
                    "action_id": duplicate["action_id"],
                },
            )

        validation = self._store.create_validation(
            workspace_id=workspace_id,
            target_object=f"route:{route_id}",
            method=f"memory_vault_bind:{view_type}",
            success_signal="route context keeps explicit memory backlink",
            weakening_signal="memory backlink conflicts with route assumptions",
        )
        action = self._store.create_memory_action(
            workspace_id=workspace_id,
            action_type="bind_to_current_route",
            memory_view_type=view_type,
            memory_result_id=memory_id,
            route_id=route_id,
            hypothesis_id=None,
            validation_id=str(validation["validation_id"]),
            request_id=request_id,
            note=note,
            memory_ref=memory_item,
        )
        self._store.emit_event(
            event_name="memory_route_bound",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="memory_vault_service",
            step="bind_to_current_route",
            status="completed",
            refs={
                "action_id": action["action_id"],
                "route_id": route_id,
                "memory_result_id": memory_id,
                "memory_view_type": view_type,
                "validation_id": validation["validation_id"],
            },
        )
        return {
            "action_id": action["action_id"],
            "action_type": "bind_to_current_route",
            "workspace_id": workspace_id,
            "route_id": route_id,
            "memory_id": memory_id,
            "memory_view_type": view_type,
            "binding_status": "bound",
            "validation_action": validation,
            "trace_refs": {
                "route_id": route_id,
                "route_version_id": route.get("version_id"),
                "memory_trace_refs": memory_item.get("trace_refs", {}),
                "memory_formal_refs": memory_item.get("formal_refs", []),
            },
            "note": note,
            "created_at": action["created_at"],
        }

    def memory_to_hypothesis_candidate(
        self,
        *,
        workspace_id: str,
        memory_id: str,
        memory_view_type: str,
        note: str | None,
        request_id: str,
    ) -> dict[str, object]:
        view_type = self._validate_view_type(memory_view_type)
        memory_item = self._resolve_memory_item(
            workspace_id=workspace_id,
            view_type=view_type,
            memory_id=memory_id,
        )
        try:
            hypothesis = self._hypothesis_service.create_candidate_from_memory(
                workspace_id=workspace_id,
                memory_view_type=view_type,
                memory_result_id=memory_id,
                memory_title=str(memory_item.get("title", "")),
                memory_snippet=str(memory_item.get("snippet", "")),
                memory_trace_refs=memory_item.get("trace_refs", {}),
                memory_formal_refs=memory_item.get("formal_refs", []),
                request_id=request_id,
                note=note,
            )
        except HypothesisServiceError as exc:
            self._raise(
                status_code=exc.status_code,
                error_code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )

        action = self._store.create_memory_action(
            workspace_id=workspace_id,
            action_type="memory_to_hypothesis_candidate",
            memory_view_type=view_type,
            memory_result_id=memory_id,
            route_id=None,
            hypothesis_id=str(hypothesis["hypothesis_id"]),
            validation_id=None,
            request_id=request_id,
            note=note,
            memory_ref=memory_item,
        )
        self._store.emit_event(
            event_name="memory_to_hypothesis_candidate_completed",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="memory_vault_service",
            step="memory_to_hypothesis_candidate",
            status="completed",
            refs={
                "action_id": action["action_id"],
                "hypothesis_id": hypothesis["hypothesis_id"],
                "memory_result_id": memory_id,
                "memory_view_type": view_type,
            },
        )
        return {
            "action_id": action["action_id"],
            "action_type": "memory_to_hypothesis_candidate",
            "workspace_id": workspace_id,
            "memory_id": memory_id,
            "memory_view_type": view_type,
            "hypothesis": hypothesis,
            "trace_refs": {
                "hypothesis_id": hypothesis["hypothesis_id"],
                "memory_trace_refs": memory_item.get("trace_refs", {}),
                "memory_formal_refs": memory_item.get("formal_refs", []),
            },
            "note": note,
            "created_at": action["created_at"],
        }

    def _validate_view_type(self, view_type: str) -> str:
        try:
            return validate_memory_view_type(view_type)
        except ValueError:
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="unsupported memory view_type",
                details={"memory_view_type": view_type},
            )
        raise AssertionError("unreachable")

    def _validate_retrieve_method(self, retrieve_method: str) -> str:
        try:
            return validate_retrieve_method(retrieve_method)
        except ValueError:
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="unsupported retrieve_method",
                details={"retrieve_method": retrieve_method},
            )
        raise AssertionError("unreachable")

    def _normalize_view_types(self, view_types: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in view_types:
            view = self._validate_view_type(raw)
            if view in seen:
                continue
            seen.add(view)
            normalized.append(view)
        return normalized

    def _normalize_filters(
        self,
        *,
        view_types: list[str],
        metadata_filters_by_view: dict[str, dict[str, object]],
    ) -> dict[str, dict[str, object]]:
        if not isinstance(metadata_filters_by_view, dict):
            self._raise(
                status_code=400,
                error_code="research.invalid_request",
                message="metadata_filters_by_view must be an object",
            )
        normalized: dict[str, dict[str, object]] = {}
        for view_type, payload in metadata_filters_by_view.items():
            resolved_view = self._validate_view_type(view_type)
            if resolved_view not in view_types:
                self._raise(
                    status_code=400,
                    error_code="research.invalid_request",
                    message="metadata filter view_type must exist in view_types",
                    details={"memory_view_type": resolved_view},
                )
            if not isinstance(payload, dict):
                self._raise(
                    status_code=400,
                    error_code="research.invalid_request",
                    message="metadata filter payload must be an object",
                    details={"memory_view_type": resolved_view},
                )
            normalized[resolved_view] = payload
        return normalized

    def _resolve_memory_item(
        self, *, workspace_id: str, view_type: str, memory_id: str
    ) -> dict[str, object]:
        resolved = self._retrieval_service.resolve_memory_item(
            workspace_id=workspace_id,
            view_type=view_type,
            result_id=memory_id,
        )
        if resolved is None:
            self._raise(
                status_code=404,
                error_code="research.not_found",
                message="memory result not found for workspace and view",
                details={
                    "workspace_id": workspace_id,
                    "memory_view_type": view_type,
                    "memory_id": memory_id,
                },
            )
        return resolved

    def supported_view_types(self) -> list[str]:
        return sorted(RETRIEVAL_VIEW_VALUES)
