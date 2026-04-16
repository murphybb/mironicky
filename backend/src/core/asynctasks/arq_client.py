"""Lightweight ARQ client helpers for request-backed background jobs."""

from __future__ import annotations

import os
from typing import Any, Optional

try:
    from arq import ArqRedis, create_pool
    from arq.connections import RedisSettings

    ARQ_IMPORT_ERROR = None
except ImportError as exc:
    create_pool = None
    ARQ_IMPORT_ERROR = exc

    class ArqRedis:  # type: ignore[no-redef]
        pass

    class RedisSettings:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            self.kwargs = kwargs

from core.observation.logger import get_logger

logger = get_logger(__name__)

_pool: Optional[ArqRedis] = None


def get_redis_settings() -> RedisSettings:
    return RedisSettings(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        database=int(os.getenv("REDIS_DB", "0")),
        password=os.getenv("REDIS_PASSWORD"),
        ssl=os.getenv("REDIS_SSL", "false").lower() == "true",
        username=os.getenv("REDIS_USERNAME"),
    )


def _require_arq() -> None:
    if create_pool is None:
        raise RuntimeError(
            "arq is required to enqueue background jobs. "
            "Install the 'arq' dependency in the active Python environment."
        ) from ARQ_IMPORT_ERROR


async def get_arq_pool() -> ArqRedis:
    global _pool
    _require_arq()
    if _pool is None:
        _pool = await create_pool(get_redis_settings())
    return _pool


async def enqueue_job(
    function_name: str,
    *args: Any,
    job_id: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    pool = await get_arq_pool()
    job = await pool.enqueue_job(function_name, *args, _job_id=job_id, **kwargs)
    logger.info("ARQ job enqueued: function=%s, job_id=%s", function_name, job_id)
    return job


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
