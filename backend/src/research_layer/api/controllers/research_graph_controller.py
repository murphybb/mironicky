from __future__ import annotations

from dataclasses import asdict

from fastapi import Query, Request

from core.di.decorators import controller
from core.interface.controller.base_controller import (
    BaseController,
    delete,
    get,
    patch,
    post,
)
from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers._utils import (
    error_payload_from_exception,
    ensure,
    get_request_id,
    parse_request_model,
    raise_http_error,
    validate_workspace_id,
)
from research_layer.api.schemas.common import ErrorResponse, ResearchErrorCode
from research_layer.api.schemas.graph import (
    GraphArchiveRequest,
    GraphArchiveResponse,
    GraphBuildResponse,
    GraphEdgeCreateRequest,
    GraphEdgePatchRequest,
    GraphEdgeResponse,
    GraphNodeCreateRequest,
    GraphNodePatchRequest,
    GraphNodeResponse,
    GraphQueryRequest,
    GraphReportResponse,
    GraphResponse,
    GraphVersionDiffResponse,
    GraphVersionListResponse,
    GraphVersionRecord,
    GraphWorkspaceResponse,
)
from research_layer.api.schemas.export import ResearchExportResponse
from research_layer.config.feature_flags import (
    EXPORT_FLAG,
    GRAPH_REPORT_FLAG,
    feature_disabled_error,
    is_feature_enabled,
)
from research_layer.graph.repository import GraphRepository
from research_layer.services.graph_build_service import GraphBuildService
from research_layer.services.graph_query_service import GraphQueryService
from research_layer.services.graph_report_service import GraphReportService
from research_layer.services.research_export_service import ResearchExportService


@controller(name="research_graph_controller")
class ResearchGraphController(BaseController):
    def __init__(self) -> None:
        super().__init__(
            prefix="/api/v1/research", tags=["Research Graph"], default_auth="none"
        )
        self._repository = GraphRepository(STORE)
        self._build_service = GraphBuildService(self._repository)
        self._query_service = GraphQueryService(self._repository)
        self._report_service = GraphReportService(STORE)
        self._export_service = ResearchExportService(STORE)

    def _create_archive_version(
        self,
        *,
        workspace_id: str,
        request_id: str,
        target_type: str,
        target_id: str,
        previous_status: str,
        reason: str | None,
    ) -> dict[str, object]:
        workspace_snapshot = self._repository.get_workspace(workspace_id)
        base_version_id = (
            str(workspace_snapshot.latest_version_id)
            if workspace_snapshot is not None and workspace_snapshot.latest_version_id
            else None
        )
        diff_payload: dict[str, object] = {
            "change_type": "graph_archive",
            "base_version_id": base_version_id,
            "new_version_id": None,
            "target_type": target_type,
            "target_id": target_id,
            "status_transition": {"from": previous_status, "to": "archived"},
            "reason": reason,
            "added": {"nodes": [], "edges": []},
            "weakened": {"nodes": [], "edges": [], "routes": []},
            "invalidated": {"nodes": [], "edges": [], "routes": []},
            "archived": {"nodes": [], "edges": [], "routes": []},
            "branch_changes": {
                "created_branch_node_ids": [],
                "created_branch_edge_ids": [],
            },
            "route_score_changes": [],
        }
        if target_type == "node":
            diff_payload["archived"]["nodes"].append(target_id)
        elif target_type == "edge":
            diff_payload["archived"]["edges"].append(target_id)
        version = self._repository.create_version(
            workspace_id=workspace_id,
            trigger_type="manual_archive",
            change_summary=f"{target_type} archived: {target_id}",
            diff_payload=diff_payload,
            request_id=request_id,
        )
        version_id = str(version["version_id"])
        diff_payload["new_version_id"] = version_id
        STORE.update_graph_version_diff_payload(
            version_id=version_id, diff_payload=diff_payload
        )
        nodes = self._repository.list_nodes(workspace_id=workspace_id)
        edges = self._repository.list_edges(workspace_id=workspace_id)
        self._repository.upsert_workspace(
            workspace_id=workspace_id,
            latest_version_id=version_id,
            status="active",
            node_count=len(nodes),
            edge_count=len(edges),
        )
        return {"version_id": version_id, "diff_payload": diff_payload}

    @post(
        "/graph/{workspace_id}/build",
        response_model=GraphBuildResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def build_graph(
        self, workspace_id: str, request: Request
    ) -> GraphBuildResponse:
        workspace = validate_workspace_id(workspace_id)
        request_id = get_request_id(request.headers.get("x-request-id"))
        result = self._build_service.build_workspace_graph(
            workspace_id=workspace, request_id=request_id
        )
        return GraphBuildResponse.model_validate(result)

    @get("/graph/{workspace_id}", response_model=GraphResponse)
    async def get_graph(self, workspace_id: str, request: Request) -> GraphResponse:
        workspace = validate_workspace_id(workspace_id)
        request_id = get_request_id(request.headers.get("x-request-id"))
        result = self._query_service.query_subgraph(
            workspace_id=workspace, center_node_id=None, max_hops=1
        )
        self._repository.emit_event(
            event_name="graph_query_completed",
            request_id=request_id,
            workspace_id=workspace,
            step="query",
            status="completed",
            metrics={
                "node_count": len(result["nodes"]),
                "edge_count": len(result["edges"]),
            },
        )
        nodes = [GraphNodeResponse.model_validate(node) for node in result["nodes"]]
        edges = [GraphEdgeResponse.model_validate(edge) for edge in result["edges"]]
        return GraphResponse(workspace_id=workspace, nodes=nodes, edges=edges)

    @get(
        "/graph/{workspace_id}/report",
        response_model=GraphReportResponse,
        responses={403: {"model": ErrorResponse}},
    )
    async def get_graph_report(self, workspace_id: str, request: Request) -> GraphReportResponse:
        request_id = get_request_id(request.headers.get("x-request-id"))
        if not is_feature_enabled(GRAPH_REPORT_FLAG):
            error = feature_disabled_error(GRAPH_REPORT_FLAG)
            self._repository.emit_event(
                event_name="graph_report_completed",
                request_id=request_id,
                workspace_id=workspace_id,
                step="report",
                status="failed",
                error={
                    "error_code": str(error["code"]),
                    "message": str(error["message"]),
                    "details": dict(error.get("details", {})),
                },
            )
            raise_http_error(**error)
        workspace = validate_workspace_id(workspace_id)
        try:
            report = self._report_service.build_report(workspace_id=workspace)
        except Exception as exc:
            self._repository.emit_event(
                event_name="graph_report_completed",
                request_id=request_id,
                workspace_id=workspace,
                step="report",
                status="failed",
                error=error_payload_from_exception(exc),
            )
            raise
        self._repository.emit_event(
            event_name="graph_report_completed",
            request_id=request_id,
            workspace_id=workspace,
            step="report",
            status="completed",
            metrics=report["summary"],
        )
        return GraphReportResponse.model_validate(report)

    @get(
        "/graph/{workspace_id}/export",
        response_model=ResearchExportResponse,
        responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    )
    async def export_graph(
        self, workspace_id: str, request: Request, format: str = Query(default="json")
    ) -> ResearchExportResponse:
        request_id = get_request_id(request.headers.get("x-request-id"))
        if not is_feature_enabled(EXPORT_FLAG):
            error = feature_disabled_error(EXPORT_FLAG)
            self._repository.emit_event(
                event_name="graph_export_completed",
                request_id=request_id,
                workspace_id=workspace_id,
                step="export",
                status="failed",
                refs={"format": format},
                error={
                    "error_code": str(error["code"]),
                    "message": str(error["message"]),
                    "details": dict(error.get("details", {})),
                },
            )
            raise_http_error(**error)
        workspace = validate_workspace_id(workspace_id)
        try:
            exported = self._export_service.export_graph(
                workspace_id=workspace, export_format=format
            )
        except ValueError as exc:
            error = {
                "error_code": ResearchErrorCode.INVALID_REQUEST.value,
                "message": str(exc),
                "details": {"format": format},
            }
            self._repository.emit_event(
                event_name="graph_export_completed",
                request_id=request_id,
                workspace_id=workspace,
                step="export",
                status="failed",
                refs={"format": format},
                error=error,
            )
            raise_http_error(
                status_code=400,
                code=error["error_code"],
                message=error["message"],
                details=error["details"],
            )
        except Exception as exc:
            self._repository.emit_event(
                event_name="graph_export_completed",
                request_id=request_id,
                workspace_id=workspace,
                step="export",
                status="failed",
                refs={"format": format},
                error=error_payload_from_exception(exc),
            )
            raise
        self._repository.emit_event(
            event_name="graph_export_completed",
            request_id=request_id,
            workspace_id=workspace,
            step="export",
            status="completed",
            refs={"format": format},
        )
        return ResearchExportResponse.model_validate(exported)

    @post(
        "/graph/{workspace_id}/query",
        response_model=GraphResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def query_graph(self, workspace_id: str, request: Request) -> GraphResponse:
        workspace = validate_workspace_id(workspace_id)
        payload = await parse_request_model(request, GraphQueryRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        ensure(
            payload.center_node_id is not None,
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="center_node_id is required for local graph query",
            details={"field": "center_node_id"},
        )
        result = self._query_service.query_subgraph(
            workspace_id=workspace,
            center_node_id=payload.center_node_id,
            max_hops=payload.max_hops,
        )
        self._repository.emit_event(
            event_name="graph_query_completed",
            request_id=request_id,
            workspace_id=workspace,
            step="query",
            status="completed",
            refs={"center_node_id": payload.center_node_id},
            metrics={
                "node_count": len(result["nodes"]),
                "edge_count": len(result["edges"]),
                "max_hops": payload.max_hops,
            },
        )
        nodes = [GraphNodeResponse.model_validate(node) for node in result["nodes"]]
        edges = [GraphEdgeResponse.model_validate(edge) for edge in result["edges"]]
        return GraphResponse(workspace_id=workspace, nodes=nodes, edges=edges)

    @get(
        "/graph/{workspace_id}/workspace",
        response_model=GraphWorkspaceResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_graph_workspace(self, workspace_id: str) -> GraphWorkspaceResponse:
        workspace = validate_workspace_id(workspace_id)
        snapshot = self._repository.get_workspace(workspace)
        ensure(
            snapshot is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="graph workspace not found",
            details={"workspace_id": workspace},
        )
        return GraphWorkspaceResponse.model_validate(asdict(snapshot))

    @post(
        "/graph/nodes",
        response_model=GraphNodeResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def create_graph_node(self, request: Request) -> GraphNodeResponse:
        payload = await parse_request_model(request, GraphNodeCreateRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        node = self._repository.create_node(
            workspace_id=payload.workspace_id,
            node_type=payload.node_type,
            object_ref_type=payload.object_ref_type,
            object_ref_id=payload.object_ref_id,
            short_label=payload.short_label,
            full_description=payload.full_description,
            short_tags=payload.short_tags,
            visibility=payload.visibility,
            source_refs=payload.source_refs,
        )
        self._repository.emit_event(
            event_name="graph_node_created",
            request_id=request_id,
            workspace_id=payload.workspace_id,
            step="node_create",
            status="completed",
            refs={"node_id": node["node_id"], "object_ref_id": payload.object_ref_id},
        )
        return GraphNodeResponse.model_validate(node)

    @patch(
        "/graph/nodes/{node_id}",
        response_model=GraphNodeResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def patch_graph_node(
        self, node_id: str, request: Request
    ) -> GraphNodeResponse:
        payload = await parse_request_model(request, GraphNodePatchRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        node = self._repository.get_node(node_id)
        ensure(
            node is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="node not found",
            details={"node_id": node_id},
        )
        ensure(
            node["workspace_id"] == payload.workspace_id,
            status_code=409,
            code=ResearchErrorCode.CONFLICT.value,
            message="workspace_id does not match node ownership",
            details={"node_id": node_id},
        )
        ensure(
            node["status"] != "archived",
            status_code=409,
            code=ResearchErrorCode.INVALID_STATE.value,
            message="archived node cannot be modified",
            details={"node_id": node_id},
        )
        try:
            updated = self._repository.update_node(
                node_id=node_id,
                short_label=payload.short_label,
                full_description=payload.full_description,
                short_tags=payload.short_tags,
                visibility=payload.visibility,
                source_refs=payload.source_refs,
                status=payload.status,
            )
        except ValueError as exc:
            raise_http_error(
                status_code=400,
                code=ResearchErrorCode.INVALID_REQUEST.value,
                message="request validation failed",
                details={"reason": str(exc)},
            )
        ensure(
            updated is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="node not found",
            details={"node_id": node_id},
        )
        self._repository.emit_event(
            event_name="graph_node_updated",
            request_id=request_id,
            workspace_id=payload.workspace_id,
            step="node_update",
            status="completed",
            refs={"node_id": node_id},
        )
        return GraphNodeResponse.model_validate(updated)

    @post(
        "/graph/edges",
        response_model=GraphEdgeResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def create_graph_edge(self, request: Request) -> GraphEdgeResponse:
        payload = await parse_request_model(request, GraphEdgeCreateRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        source_node = self._repository.get_node(payload.source_node_id)
        target_node = self._repository.get_node(payload.target_node_id)
        ensure(
            source_node is not None and target_node is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="edge endpoints not found",
            details={
                "source_node_id": payload.source_node_id,
                "target_node_id": payload.target_node_id,
            },
        )
        ensure(
            source_node["workspace_id"] == payload.workspace_id
            and target_node["workspace_id"] == payload.workspace_id,
            status_code=409,
            code=ResearchErrorCode.CONFLICT.value,
            message="edge endpoints belong to a different workspace",
            details={"workspace_id": payload.workspace_id},
        )
        edge = self._repository.create_edge(
            workspace_id=payload.workspace_id,
            source_node_id=payload.source_node_id,
            target_node_id=payload.target_node_id,
            edge_type=payload.edge_type,
            object_ref_type=payload.object_ref_type,
            object_ref_id=payload.object_ref_id,
            strength=payload.strength,
        )
        self._repository.emit_event(
            event_name="graph_edge_created",
            request_id=request_id,
            workspace_id=payload.workspace_id,
            step="edge_create",
            status="completed",
            refs={"edge_id": edge["edge_id"]},
        )
        return GraphEdgeResponse.model_validate(edge)

    @patch(
        "/graph/edges/{edge_id}",
        response_model=GraphEdgeResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def patch_graph_edge(
        self, edge_id: str, request: Request
    ) -> GraphEdgeResponse:
        payload = await parse_request_model(request, GraphEdgePatchRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        edge = self._repository.get_edge(edge_id)
        ensure(
            edge is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="edge not found",
            details={"edge_id": edge_id},
        )
        ensure(
            edge["workspace_id"] == payload.workspace_id,
            status_code=409,
            code=ResearchErrorCode.CONFLICT.value,
            message="workspace_id does not match edge ownership",
            details={"edge_id": edge_id},
        )
        ensure(
            edge["status"] != "archived",
            status_code=409,
            code=ResearchErrorCode.INVALID_STATE.value,
            message="archived edge cannot be modified",
            details={"edge_id": edge_id},
        )
        try:
            updated = self._repository.update_edge(
                edge_id=edge_id, status=payload.status, strength=payload.strength
            )
        except ValueError as exc:
            raise_http_error(
                status_code=400,
                code=ResearchErrorCode.INVALID_REQUEST.value,
                message="request validation failed",
                details={"reason": str(exc)},
            )
        ensure(
            updated is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="edge not found",
            details={"edge_id": edge_id},
        )
        self._repository.emit_event(
            event_name="graph_edge_updated",
            request_id=request_id,
            workspace_id=payload.workspace_id,
            step="edge_update",
            status="completed",
            refs={"edge_id": edge_id},
        )
        return GraphEdgeResponse.model_validate(updated)

    @delete(
        "/graph/nodes/{node_id}",
        response_model=GraphArchiveResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def archive_graph_node(
        self, node_id: str, request: Request
    ) -> GraphArchiveResponse:
        payload = await parse_request_model(request, GraphArchiveRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        node = self._repository.get_node(node_id)
        ensure(
            node is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="node not found",
            details={"node_id": node_id},
        )
        ensure(
            node["workspace_id"] == payload.workspace_id,
            status_code=409,
            code=ResearchErrorCode.CONFLICT.value,
            message="workspace_id does not match node ownership",
            details={"node_id": node_id},
        )
        ensure(
            node["status"] != "archived",
            status_code=409,
            code=ResearchErrorCode.INVALID_STATE.value,
            message="node is already archived",
            details={"node_id": node_id},
        )
        updated = self._repository.update_node(
            node_id=node_id, short_label=None, full_description=None, status="archived"
        )
        ensure(
            updated is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="node not found",
            details={"node_id": node_id},
        )
        version = self._create_archive_version(
            workspace_id=payload.workspace_id,
            request_id=request_id,
            target_type="node",
            target_id=node_id,
            previous_status=str(node["status"]),
            reason=payload.reason,
        )
        self._repository.emit_event(
            event_name="graph_node_archived",
            request_id=request_id,
            workspace_id=payload.workspace_id,
            step="node_archive",
            status="completed",
            refs={"node_id": node_id, "version_id": version["version_id"]},
        )
        return GraphArchiveResponse(
            workspace_id=payload.workspace_id,
            target_type="node",
            target_id=node_id,
            status="archived",
            version_id=version["version_id"],
            diff_payload=version["diff_payload"],
        )

    @delete(
        "/graph/edges/{edge_id}",
        response_model=GraphArchiveResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def archive_graph_edge(
        self, edge_id: str, request: Request
    ) -> GraphArchiveResponse:
        payload = await parse_request_model(request, GraphArchiveRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        edge = self._repository.get_edge(edge_id)
        ensure(
            edge is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="edge not found",
            details={"edge_id": edge_id},
        )
        ensure(
            edge["workspace_id"] == payload.workspace_id,
            status_code=409,
            code=ResearchErrorCode.CONFLICT.value,
            message="workspace_id does not match edge ownership",
            details={"edge_id": edge_id},
        )
        ensure(
            edge["status"] != "archived",
            status_code=409,
            code=ResearchErrorCode.INVALID_STATE.value,
            message="edge is already archived",
            details={"edge_id": edge_id},
        )
        updated = self._repository.update_edge(
            edge_id=edge_id, status="archived", strength=None
        )
        ensure(
            updated is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="edge not found",
            details={"edge_id": edge_id},
        )
        version = self._create_archive_version(
            workspace_id=payload.workspace_id,
            request_id=request_id,
            target_type="edge",
            target_id=edge_id,
            previous_status=str(edge["status"]),
            reason=payload.reason,
        )
        self._repository.emit_event(
            event_name="graph_edge_archived",
            request_id=request_id,
            workspace_id=payload.workspace_id,
            step="edge_archive",
            status="completed",
            refs={"edge_id": edge_id, "version_id": version["version_id"]},
        )
        return GraphArchiveResponse(
            workspace_id=payload.workspace_id,
            target_type="edge",
            target_id=edge_id,
            status="archived",
            version_id=version["version_id"],
            diff_payload=version["diff_payload"],
        )

    @get("/versions", response_model=GraphVersionListResponse)
    async def list_versions(
        self, workspace_id: str | None = Query(default=None)
    ) -> GraphVersionListResponse:
        workspace = validate_workspace_id(workspace_id)
        items = [
            GraphVersionRecord.model_validate(version)
            for version in self._repository.list_versions(workspace_id=workspace)
        ]
        return GraphVersionListResponse(items=items, total=len(items))

    @get(
        "/versions/{version_id}/diff",
        response_model=GraphVersionDiffResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_version_diff(self, version_id: str) -> GraphVersionDiffResponse:
        version = self._repository.get_version(version_id)
        ensure(
            version is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="version not found",
            details={"version_id": version_id},
        )
        return GraphVersionDiffResponse(
            version_id=version_id,
            workspace_id=version["workspace_id"],
            diff_payload=version["diff_payload"],
        )
