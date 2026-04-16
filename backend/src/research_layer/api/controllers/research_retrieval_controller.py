from __future__ import annotations

from fastapi import Request

from core.di.decorators import controller
from core.interface.controller.base_controller import BaseController, post
from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers._utils import (
    get_request_id,
    parse_request_model,
    raise_http_error,
)
from research_layer.api.schemas.common import ErrorResponse
from research_layer.api.schemas.memory import (
    MemoryBindToCurrentRouteRequest,
    MemoryBindToCurrentRouteResponse,
    MemoryListRequest,
    MemoryListResponse,
    MemoryToHypothesisCandidateRequest,
    MemoryToHypothesisCandidateResponse,
)
from research_layer.api.schemas.retrieval import RetrievalViewRequest, RetrievalViewResponse
from research_layer.services.memory_vault_service import (
    MemoryVaultService,
    MemoryVaultServiceError,
)
from research_layer.services.retrieval_views_service import (
    ResearchRetrievalService,
    RetrievalServiceError,
)


@controller(name="research_retrieval_controller")
class ResearchRetrievalController(BaseController):
    def __init__(self) -> None:
        super().__init__(
            prefix="/api/v1/research",
            tags=["Research Retrieval"],
            default_auth="none",
        )
        self._retrieval_service = ResearchRetrievalService(STORE)
        self._memory_vault_service = MemoryVaultService(STORE)

    @post(
        "/retrieval/views/{view_type}",
        response_model=RetrievalViewResponse,
        responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def retrieve_view(self, view_type: str, request: Request) -> RetrievalViewResponse:
        payload = await parse_request_model(request, RetrievalViewRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            result = self._retrieval_service.retrieve(
                workspace_id=payload.workspace_id,
                view_type=view_type,
                query=payload.query,
                retrieve_method=payload.retrieve_method,
                top_k=payload.top_k,
                metadata_filters=payload.metadata_filters,
                request_id=request_id,
            )
        except RetrievalServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return RetrievalViewResponse.model_validate(result)

    @post(
        "/memory/list",
        response_model=MemoryListResponse,
        responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def list_memory(self, request: Request) -> MemoryListResponse:
        payload = await parse_request_model(request, MemoryListRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            result = self._memory_vault_service.list_memory(
                workspace_id=payload.workspace_id,
                view_types=payload.view_types,
                query=payload.query,
                retrieve_method=payload.retrieve_method,
                top_k_per_view=payload.top_k_per_view,
                metadata_filters_by_view=payload.metadata_filters_by_view,
                request_id=request_id,
            )
        except MemoryVaultServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return MemoryListResponse.model_validate(result)

    @post(
        "/memory/actions/bind-to-current-route",
        response_model=MemoryBindToCurrentRouteResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def bind_memory_to_current_route(
        self, request: Request
    ) -> MemoryBindToCurrentRouteResponse:
        payload = await parse_request_model(request, MemoryBindToCurrentRouteRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            result = self._memory_vault_service.bind_to_current_route(
                workspace_id=payload.workspace_id,
                route_id=payload.route_id,
                memory_id=payload.memory_id,
                memory_view_type=payload.memory_view_type,
                note=payload.note,
                request_id=request_id,
            )
        except MemoryVaultServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return MemoryBindToCurrentRouteResponse.model_validate(result)

    @post(
        "/memory/actions/memory-to-hypothesis-candidate",
        response_model=MemoryToHypothesisCandidateResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    async def memory_to_hypothesis_candidate(
        self, request: Request
    ) -> MemoryToHypothesisCandidateResponse:
        payload = await parse_request_model(request, MemoryToHypothesisCandidateRequest)
        request_id = get_request_id(request.headers.get("x-request-id"))
        try:
            result = self._memory_vault_service.memory_to_hypothesis_candidate(
                workspace_id=payload.workspace_id,
                memory_id=payload.memory_id,
                memory_view_type=payload.memory_view_type,
                note=payload.note,
                request_id=request_id,
            )
        except MemoryVaultServiceError as exc:
            raise_http_error(
                status_code=exc.status_code,
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
            )
        return MemoryToHypothesisCandidateResponse.model_validate(result)
