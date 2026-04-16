"""Global exception handler with research-specific error envelope normalization."""

from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from common_utils.datetime_utils import get_now_with_timezone, to_iso_format
from core.constants.errors import ErrorCode, ErrorStatus
from core.observation.logger import get_logger
from research_layer.api.schemas.common import ResearchErrorCode

logger = get_logger(__name__)
_RESEARCH_API_PREFIX = "/api/v1/research"


def _is_research_request(request: Request) -> bool:
    return str(request.url.path).startswith(_RESEARCH_API_PREFIX)


def _request_value_or_default(raw: str | None, prefix: str) -> str:
    if raw and raw.strip():
        return raw.strip()
    return f"{prefix}_{uuid4().hex[:12]}"


def _resolve_trace_id(request: Request, detail: dict[str, object]) -> str:
    trace_id = detail.get("trace_id")
    if isinstance(trace_id, str) and trace_id.strip():
        return trace_id.strip()
    state_trace_id = getattr(request.state, "trace_id", None)
    if isinstance(state_trace_id, str) and state_trace_id.strip():
        return state_trace_id.strip()
    return _request_value_or_default(request.headers.get("x-trace-id"), "trace")


def _resolve_request_id(request: Request, detail: dict[str, object]) -> str:
    request_id = detail.get("request_id")
    if isinstance(request_id, str) and request_id.strip():
        return request_id.strip()
    return _request_value_or_default(request.headers.get("x-request-id"), "req")


def _default_research_error_code(status_code: int) -> str:
    mapping = {
        400: ResearchErrorCode.INVALID_REQUEST.value,
        403: ResearchErrorCode.FORBIDDEN.value,
        404: ResearchErrorCode.NOT_FOUND.value,
        409: ResearchErrorCode.CONFLICT.value,
        429: ResearchErrorCode.LLM_RATE_LIMITED.value,
        500: ResearchErrorCode.INTERNAL_ERROR.value,
        502: ResearchErrorCode.LLM_FAILED.value,
        503: ResearchErrorCode.SCHOLARLY_PROVIDER_UNAVAILABLE.value,
        504: ResearchErrorCode.LLM_TIMEOUT.value,
    }
    return mapping.get(status_code, ResearchErrorCode.INTERNAL_ERROR.value)


def _build_research_envelope(
    request: Request,
    *,
    status_code: int,
    detail: object,
    fallback_message: str,
) -> dict[str, object]:
    detail_dict = detail if isinstance(detail, dict) else {}
    details = detail_dict.get("details")
    normalized_details = details if isinstance(details, dict) else {}
    error_code = detail_dict.get("error_code")
    normalized_error_code = (
        str(error_code)
        if isinstance(error_code, str) and error_code.strip()
        else _default_research_error_code(status_code)
    )
    message = detail_dict.get("message")
    normalized_message = (
        str(message).strip()
        if isinstance(message, str) and message.strip()
        else fallback_message
    )
    provider = detail_dict.get("provider")
    normalized_provider = provider if isinstance(provider, str) else None
    degraded = detail_dict.get("degraded")
    normalized_degraded = degraded if isinstance(degraded, bool) else False

    return {
        "error_code": normalized_error_code,
        "message": normalized_message,
        "details": normalized_details,
        "trace_id": _resolve_trace_id(request, detail_dict),
        "request_id": _resolve_request_id(request, detail_dict),
        "provider": normalized_provider,
        "degraded": normalized_degraded,
    }


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Global exception handler

    Handles all exceptions uniformly, including HTTPException and other exceptions,
    ensuring they are properly formatted and returned to the client.

    Args:
        request: FastAPI request object
        exc: Exception object

    Returns:
        JSONResponse: Formatted error response
    """
    # Handle HTTP exceptions
    if isinstance(exc, HTTPException):
        logger.warning(
            "HTTP exception: %s %s - Status code: %d, Detail: %s",
            request.method,
            str(request.url),
            exc.status_code,
            exc.detail,
        )
        if _is_research_request(request):
            return JSONResponse(
                status_code=exc.status_code,
                content=_build_research_envelope(
                    request,
                    status_code=exc.status_code,
                    detail=exc.detail,
                    fallback_message="request failed",
                ),
            )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": ErrorStatus.FAILED.value,
                "code": ErrorCode.HTTP_ERROR.value,
                "message": exc.detail,
                "timestamp": to_iso_format(get_now_with_timezone()),
                "path": str(request.url.path),
            },
        )

    # Handle other exceptions
    logger.error(
        "Unhandled exception: %s %s - Exception type: %s, Detail: %s",
        request.method,
        str(request.url),
        type(exc).__name__,
        str(exc),
        exc_info=True,
    )
    if _is_research_request(request):
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content=_build_research_envelope(
                request,
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "details": {"exception_type": type(exc).__name__},
                },
                fallback_message="Internal server error",
            ),
        )

    return JSONResponse(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": ErrorStatus.FAILED.value,
            "code": ErrorCode.SYSTEM_ERROR.value,
            "message": "Internal server error",
            "timestamp": to_iso_format(get_now_with_timezone()),
            "path": str(request.url.path),
        },
    )
