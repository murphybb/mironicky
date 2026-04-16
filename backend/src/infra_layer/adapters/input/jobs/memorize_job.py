"""ARQ jobs for formal memorize runtime execution."""

from __future__ import annotations

import time
from typing import Any, Dict

from agentic_layer.memory_manager import MemoryManager
from api_specs.request_converter import convert_simple_message_to_memorize_request
from core.context.context import clear_current_app_info, set_current_app_info
from core.di import get_bean_by_type
from core.observation.logger import get_logger
from core.tenants.request_tenant_provider import RequestTenantInfo
from service.request_status_service import RequestStatusService

logger = get_logger(__name__)


async def run_memorize_single_message_job(
    message_data: Dict[str, Any],
    request_status_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute memorize processing in the worker and close request status."""
    request_id = request_status_context["request_id"]
    tenant_info = RequestTenantInfo(
        tenant_key_prefix=request_status_context["tenant_key_prefix"]
    )
    request_start_time_ms = request_status_context.get("request_start_time_ms")
    request_status_service = get_bean_by_type(RequestStatusService)
    app_info_token = set_current_app_info(
        {
            "request_id": request_id,
            "request_start_time_ms": request_start_time_ms,
        }
    )

    try:
        memorize_request = await convert_simple_message_to_memorize_request(message_data)
        memory_count = await MemoryManager().memorize(memorize_request)

        end_time_ms = int(time.time() * 1000)
        time_ms = None
        if isinstance(request_start_time_ms, int):
            time_ms = max(end_time_ms - request_start_time_ms, 0)

        await request_status_service.update_request_status(
            tenant_info=tenant_info,
            request_id=request_id,
            status="success",
            url=request_status_context.get("url"),
            method=request_status_context.get("method"),
            http_code=200,
            time_ms=time_ms,
            error_message=None,
            timestamp=end_time_ms,
        )
        logger.info(
            "Memorize worker job completed: request_id=%s, memory_count=%s",
            request_id,
            memory_count,
        )
        return {"request_id": request_id, "memory_count": memory_count}
    except Exception as exc:
        end_time_ms = int(time.time() * 1000)
        time_ms = None
        if isinstance(request_start_time_ms, int):
            time_ms = max(end_time_ms - request_start_time_ms, 0)

        await request_status_service.update_request_status(
            tenant_info=tenant_info,
            request_id=request_id,
            status="failed",
            url=request_status_context.get("url"),
            method=request_status_context.get("method"),
            http_code=500,
            time_ms=time_ms,
            error_message=str(exc),
            timestamp=end_time_ms,
        )
        logger.error(
            "Memorize worker job failed: request_id=%s, error=%s",
            request_id,
            exc,
            exc_info=True,
        )
        raise
    finally:
        clear_current_app_info(app_info_token)


async def memorize_single_message_job(
    ctx: Dict[str, Any],
    message_data: Dict[str, Any],
    request_status_context: Dict[str, Any],
) -> Dict[str, Any]:
    """ARQ entrypoint for single-message memorize execution."""
    del ctx
    return await run_memorize_single_message_job(
        message_data=message_data,
        request_status_context=request_status_context,
    )
