from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

WORKSPACE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_\-:.]{2,63}$"


class ResearchErrorCode(str, Enum):
    INVALID_REQUEST = "research.invalid_request"
    NOT_FOUND = "research.not_found"
    INVALID_STATE = "research.invalid_state"
    CONFLICT = "research.conflict"
    LLM_FAILED = "research.llm_failed"
    LLM_TIMEOUT = "research.llm_timeout"
    LLM_RATE_LIMITED = "research.llm_rate_limited"
    LLM_AUTH_FAILED = "research.llm_auth_failed"
    LLM_INVALID_OUTPUT = "research.llm_invalid_output"
    LLM_TRACE_MISSING = "research.llm_trace_missing"
    FORBIDDEN = "research.forbidden"
    VISIBILITY_VIOLATION = "research.visibility_violation"
    PACKAGE_VISIBILITY_VIOLATION = "research.package_visibility_violation"
    FAILURE_ATTACH_INVALID_TARGET = "research.failure_attach_invalid_target"
    INTERNAL_ERROR = "research.internal_error"
    RECOMPUTE_FAILED = "research.recompute_failed"
    VERSION_DIFF_UNAVAILABLE = "research.version_diff_unavailable"
    PACKAGE_PUBLISH_FAILED = "research.package_publish_failed"
    SCHOLARLY_PROVIDER_UNAVAILABLE = "research.scholarly_provider_unavailable"
    SCHOLARLY_PROVIDER_MISCONFIGURED = "research.scholarly_provider_misconfigured"
    BOOTSTRAP_LIVE_LLM_DISABLED = "research.bootstrap_live_llm_disabled"
    FIXTURE_LIVE_LLM_NOT_ALLOWED = "research.fixture_live_llm_not_allowed"
    SOURCE_IMPORT_REMOTE_FETCH_FAILED = "research.source_import_remote_fetch_failed"
    SOURCE_IMPORT_PARSE_FAILED = "research.source_import_parse_failed"
    SOURCE_IMPORT_UNSUPPORTED_FORMAT = "research.source_import_unsupported_format"


class WorkspaceScopedBody(BaseModel):
    workspace_id: str = Field(pattern=WORKSPACE_ID_PATTERN)


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)
    trace_id: str
    request_id: str
    provider: str | None = None
    degraded: bool = False


class LLMUsage(BaseModel):
    prompt_tokens: int | float | str | None = None
    completion_tokens: int | float | str | None = None
    total_tokens: int | float | str | None = None


class LLMTrace(BaseModel):
    provider_backend: str | None = None
    provider_model: str | None = None
    request_id: str | None = None
    llm_response_id: str | None = None
    usage: LLMUsage | None = None
    fallback_used: bool = False
    degraded: bool = False
    degraded_reason: str | None = None


class ResultRef(BaseModel):
    resource_type: str
    resource_id: str


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobError(BaseModel):
    error_code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class AsyncJobAcceptedResponse(BaseModel):
    job_id: str
    job_type: str
    status: JobStatus
    workspace_id: str
    status_url: str


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    job_type: str
    status: JobStatus
    workspace_id: str
    request_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_ref: ResultRef | None = None
    error: JobError | None = None
