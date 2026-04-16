from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from threading import Thread
from typing import Any

from research_layer.api.controllers._state_store import STORE

logger = logging.getLogger(__name__)

_ACTIVE_BACKGROUND_THREADS: set[Thread] = set()
_ACTIVE_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()
_TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


def _mark_job_failed_on_crash(*, job_id: str, job_type: str, exc: Exception) -> None:
    try:
        job = STORE.get_job(job_id)
        if job is None:
            return
        status = str(job.get("status") or "").lower()
        if status in _TERMINAL_JOB_STATUSES:
            return
        error = {
            "error_code": "research.job_crashed",
            "message": "background job crashed before terminal status",
            "details": {
                "job_type": job_type,
                "reason": str(exc),
                "exception_type": type(exc).__name__,
            },
        }
        STORE.finish_job_failed(job_id=job_id, error=error)
        STORE.emit_event(
            event_name="job_failed",
            request_id=str(job.get("request_id") or ""),
            job_id=job_id,
            workspace_id=str(job.get("workspace_id") or ""),
            component="_job_runner",
            step="background_dispatch",
            status="failed",
            error=error,
        )
    except Exception:
        logger.exception(
            "failed to persist background job crash status",
            extra={"job_id": job_id, "job_type": job_type},
        )


def schedule_background_job(
    coroutine: Coroutine[Any, Any, None], *, job_id: str, job_type: str
) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        task = loop.create_task(
            coroutine, name=f"research-job-{job_type}-{job_id}"
        )
        _ACTIVE_BACKGROUND_TASKS.add(task)

        def _on_done(done: asyncio.Task[Any]) -> None:
            _ACTIVE_BACKGROUND_TASKS.discard(done)
            try:
                done.result()
            except Exception as exc:
                logger.exception(
                    "research background job crashed",
                    extra={"job_id": job_id, "job_type": job_type},
                )
                _mark_job_failed_on_crash(job_id=job_id, job_type=job_type, exc=exc)

        task.add_done_callback(_on_done)
        return

    def _run_in_thread() -> None:
        try:
            asyncio.run(coroutine)
        except Exception as exc:
            logger.exception(
                "research background job crashed",
                extra={"job_id": job_id, "job_type": job_type},
            )
            _mark_job_failed_on_crash(job_id=job_id, job_type=job_type, exc=exc)
        finally:
            _ACTIVE_BACKGROUND_THREADS.discard(thread)

    thread = Thread(
        target=_run_in_thread,
        name=f"research-job-{job_type}-{job_id}",
        daemon=True,
    )
    _ACTIVE_BACKGROUND_THREADS.add(thread)
    thread.start()
