from __future__ import annotations

from core.di.decorators import controller
from core.interface.controller.base_controller import BaseController, get
from research_layer.api.controllers._state_store import STORE
from research_layer.api.controllers._utils import ensure
from research_layer.api.schemas.common import ErrorResponse, JobStatusResponse, ResearchErrorCode


@controller(name="research_job_controller")
class ResearchJobController(BaseController):
    def __init__(self) -> None:
        super().__init__(
            prefix="/api/v1/research",
            tags=["Research Job"],
            default_auth="none",
        )

    @get(
        "/jobs/{job_id}",
        response_model=JobStatusResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_job_status(self, job_id: str) -> JobStatusResponse:
        job = STORE.get_job(job_id)
        ensure(
            job is not None,
            status_code=404,
            code=ResearchErrorCode.NOT_FOUND.value,
            message="job not found",
            details={"job_id": job_id},
        )
        return JobStatusResponse.model_validate(job)
