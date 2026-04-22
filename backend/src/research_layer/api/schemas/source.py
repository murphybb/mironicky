from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from research_layer.api.schemas.common import WorkspaceScopedBody

SOURCE_TYPE_VALUES = {"paper", "note", "feedback", "failure_record", "dialogue"}
CANDIDATE_TYPE_VALUES = {
    "evidence",
    "assumption",
    "conflict",
    "failure",
    "validation",
    "conclusion",
    "gap",
}
CANDIDATE_STATUS_VALUES = {"pending", "confirmed", "rejected"}
SOURCE_INPUT_MODE_VALUES = {"auto", "manual_text", "url", "local_file"}


class SourceLocalFileInput(BaseModel):
    file_name: str = Field(min_length=1, max_length=512)
    file_content_base64: str | None = None
    local_path: str | None = None
    mime_type: str | None = None


class SourceImportRequest(WorkspaceScopedBody):
    source_type: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=256)
    content: str | None = None
    source_input_mode: Literal["auto", "manual_text", "url", "local_file"] = "auto"
    source_input: str | None = None
    source_url: str | None = None
    local_file: SourceLocalFileInput | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class SourceResponse(BaseModel):
    source_id: str
    workspace_id: str
    source_type: str
    title: str
    content: str
    normalized_content: str | None = None
    status: str
    metadata: dict[str, object]
    import_request_id: str | None = None
    last_extract_job_id: str | None = None
    last_candidate_batch_id: str | None = None
    last_extract_status: str | None = None
    last_extract_error: dict[str, object] | None = None
    created_at: datetime
    updated_at: datetime


class SourceListResponse(BaseModel):
    items: list[SourceResponse]
    total: int


class SourceExtractRequest(WorkspaceScopedBody):
    async_mode: bool = True


class BootstrapCandidateInput(BaseModel):
    candidate_type: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_span: dict[str, object] = Field(default_factory=dict)


class BootstrapMaterialInput(BaseModel):
    source_type: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1)
    metadata: dict[str, object] = Field(default_factory=dict)
    provenance: dict[str, object] = Field(default_factory=dict)
    candidates: list[BootstrapCandidateInput] = Field(default_factory=list)


class SourceBootstrapRequest(WorkspaceScopedBody):
    materials: list[BootstrapMaterialInput] = Field(min_length=1)
    run_extract: bool = False


class SourceBootstrapResponse(BaseModel):
    workspace_id: str
    status: str
    imported_count: int
    failed_count: int
    items: list[dict[str, object]]
    failures: list[dict[str, object]]


class CandidateRecord(BaseModel):
    candidate_id: str
    workspace_id: str
    source_id: str
    candidate_type: str
    semantic_type: str | None = None
    text: str
    status: str
    source_span: dict[str, object]
    quote: str | None = None
    trace_refs: dict[str, object] = Field(default_factory=dict)
    candidate_batch_id: str | None = None
    extraction_job_id: str | None = None
    extractor_name: str | None = None
    reject_reason: str | None = None
    provider_backend: str | None = None
    provider_model: str | None = None
    request_id: str | None = None
    llm_response_id: str | None = None
    usage: dict[str, object] | None = None
    fallback_used: bool = False
    degraded: bool = False
    degraded_reason: str | None = None


class CandidateDetailResponse(CandidateRecord):
    pass


class CandidateListResponse(BaseModel):
    items: list[CandidateRecord]
    total: int


class CandidateConfirmRequest(WorkspaceScopedBody):
    candidate_ids: list[str] = Field(min_length=1)


class CandidateRejectRequest(WorkspaceScopedBody):
    candidate_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=256)


class CandidateActionResponse(BaseModel):
    updated_ids: list[str]
    status: str


class ExtractionResultResponse(BaseModel):
    candidate_batch_id: str
    workspace_id: str
    source_id: str
    job_id: str
    request_id: str | None = None
    candidate_ids: list[str]
    status: str
    error: dict[str, object] | None = None
    provider_backend: str | None = None
    provider_model: str | None = None
    llm_request_id: str | None = None
    llm_response_id: str | None = None
    usage: dict[str, object] | None = None
    fallback_used: bool = False
    degraded: bool = False
    degraded_reason: str | None = None
    partial_failure_count: int = 0
    created_at: datetime
    finished_at: datetime | None = None
