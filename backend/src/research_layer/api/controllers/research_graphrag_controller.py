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
from research_layer.api.schemas.common import ErrorResponse, ResearchErrorCode
from research_layer.api.schemas.graphrag import (
    GraphRAGQueryRequest,
    GraphRAGQueryResponse,
)
from research_layer.services.graphrag_service import GraphRAGService


@controller(name="research_graphrag_controller")
class ResearchGraphRAGController(BaseController):
    def __init__(self) -> None:
        super().__init__(
            prefix="/api/v1/research",
            tags=["Research GraphRAG"],
            default_auth="none",
        )
        self._service = GraphRAGService(STORE)

    @post(
        "/graphrag/query",
        response_model=GraphRAGQueryResponse,
        responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def query(self, request: Request) -> GraphRAGQueryResponse:
        payload = await parse_request_model(request, GraphRAGQueryRequest)
        question = payload.question.strip()
        if not question:
            raise_http_error(
                status_code=400,
                code=ResearchErrorCode.INVALID_REQUEST.value,
                message="request validation failed",
                details={
                    "errors": [
                        {"loc": ["question"], "msg": "question must not be blank"}
                    ]
                },
            )
        result = self._service.answer(
            workspace_id=payload.workspace_id,
            question=question,
            request_id=get_request_id(request.headers.get("x-request-id")),
            limit=payload.limit,
        )
        return GraphRAGQueryResponse.model_validate(result)
