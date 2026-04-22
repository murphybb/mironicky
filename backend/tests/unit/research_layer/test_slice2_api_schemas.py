from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from research_layer.api.controllers._utils import validate_workspace_id
from research_layer.api.schemas.common import ErrorResponse, WorkspaceScopedBody
from research_layer.api.schemas.graph import GraphArchiveRequest, GraphArchiveResponse
from research_layer.api.schemas.hypothesis import (
    HypothesisListResponse,
    HypothesisResponse,
)
from research_layer.api.schemas.source import (
    CandidateRecord,
    SourceImportRequest,
    SourceListResponse,
    SourceResponse,
)
from research_layer.services.argument_graph_types import (
    normalize_relation_type,
    normalize_unit_type,
)


@pytest.mark.parametrize("workspace_id", ["ws_alpha-01", "ws:alpha.01", "a" * 64])
def test_workspace_scoped_body_accepts_valid_workspace_id(workspace_id: str) -> None:
    body = WorkspaceScopedBody(workspace_id=workspace_id)
    assert body.workspace_id == workspace_id


@pytest.mark.parametrize(
    "workspace_id",
    ["", "ab", "white space", "invalid*", ":ab", ".ab", "_ab", "-ab", "a" * 65],
)
def test_workspace_scoped_body_rejects_invalid_workspace_id(workspace_id: str) -> None:
    with pytest.raises(ValidationError):
        WorkspaceScopedBody(workspace_id=workspace_id)


@pytest.mark.parametrize("workspace_id", ["ws:alpha.01", "a" * 64])
def test_validate_workspace_id_accepts_domain_valid_values(workspace_id: str) -> None:
    assert validate_workspace_id(workspace_id) == workspace_id


@pytest.mark.parametrize("workspace_id", [None, ":ab", ".ab", "_ab", "-ab", "a" * 65])
def test_validate_workspace_id_rejects_domain_invalid_values(
    workspace_id: str | None,
) -> None:
    with pytest.raises(HTTPException):
        validate_workspace_id(workspace_id)


def test_source_list_response_schema_shape() -> None:
    item = SourceResponse(
        source_id="src_001",
        workspace_id="ws_alpha_01",
        source_type="paper",
        title="Paper A",
        content="content",
        status="raw",
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    payload = SourceListResponse(items=[item], total=1)
    assert payload.total == 1
    assert payload.items[0].source_id == "src_001"


def test_source_import_request_supports_url_mode_inputs() -> None:
    payload = SourceImportRequest(
        workspace_id="ws_alpha_01",
        source_type="paper",
        source_input_mode="url",
        source_url="https://example.org/paper/123",
    )
    assert payload.source_input_mode == "url"
    assert payload.source_url == "https://example.org/paper/123"


def test_source_import_request_supports_local_file_inputs() -> None:
    payload = SourceImportRequest(
        workspace_id="ws_alpha_01",
        source_type="paper",
        source_input_mode="local_file",
        local_file={
            "file_name": "paper.docx",
            "file_content_base64": "dGVzdA==",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    )
    assert payload.local_file is not None
    assert payload.local_file.file_name == "paper.docx"
    assert payload.source_input_mode == "local_file"


def test_source_import_request_rejects_unknown_input_mode() -> None:
    with pytest.raises(ValidationError):
        SourceImportRequest(
            workspace_id="ws_alpha_01",
            source_type="paper",
            source_input_mode="clipboard",
            source_input="https://example.org/paper/123",
        )


def test_prompt_b_type_maps_match_graph_compatible_types() -> None:
    assert normalize_unit_type("claim") == "conclusion"
    assert normalize_unit_type("evidence") == "evidence"
    assert normalize_unit_type("premise") == "assumption"
    assert normalize_unit_type("contradiction") == "conflict"
    assert normalize_unit_type("open_question") == "gap"
    assert normalize_relation_type("supports") == "supports"
    assert normalize_relation_type("relies_on") == "requires"
    assert normalize_relation_type("contradicts") == "conflicts"
    assert normalize_relation_type("leads_to") == "derives"


def test_candidate_record_accepts_prompt_b_semantic_metadata() -> None:
    record = CandidateRecord(
        candidate_id="cand_1",
        workspace_id="ws_alpha_01",
        source_id="src_1",
        candidate_type="conclusion",
        semantic_type="claim",
        text="研究结论需要由证据支撑。",
        quote="研究结论需要由证据支撑。",
        source_span={"page": 2, "block_id": "p2-b3", "paragraph_id": "p2-b3-par0"},
        trace_refs={"block_id": "p2-b3"},
        status="pending",
    )

    assert record.candidate_type == "conclusion"
    assert record.semantic_type == "claim"
    assert record.quote == "研究结论需要由证据支撑。"
    assert record.source_span["block_id"] == "p2-b3"


def test_graph_archive_request_and_response_schema_shape() -> None:
    request = GraphArchiveRequest(
        workspace_id="ws_alpha_01", reason="archive from workbench delete"
    )
    response = GraphArchiveResponse(
        workspace_id="ws_alpha_01",
        target_type="node",
        target_id="node_001",
        status="archived",
        version_id="ver_001",
        diff_payload={"archived": {"nodes": ["node_001"], "edges": [], "routes": []}},
    )
    assert request.workspace_id == "ws_alpha_01"
    assert response.target_type == "node"


def test_hypothesis_list_response_supports_deferred_status() -> None:
    item = HypothesisResponse.model_validate(
        {
            "hypothesis_id": "hyp_001",
            "workspace_id": "ws_alpha_01",
            "title": "Deferred hypothesis",
            "summary": "summary",
            "premise": "premise",
            "rationale": "rationale",
            "status": "deferred",
            "stage": "exploratory",
            "trigger_object_ids": [],
            "trigger_refs": [],
            "related_object_ids": [],
            "novelty_typing": "incremental",
            "minimum_validation_action": {
                "validation_id": "val_001",
                "target_object": "node:node_001",
                "method": "manual check",
                "success_signal": "signal",
                "weakening_signal": "weak",
                "cost_level": "low",
                "time_level": "low",
            },
            "weakening_signal": {
                "signal_type": "gap",
                "signal_text": "text",
                "severity_hint": "medium",
                "trace_refs": {},
            },
        }
    )
    payload = HypothesisListResponse(items=[item], total=1)
    assert payload.items[0].status == "deferred"


def test_error_response_target_envelope_fields_are_frozen() -> None:
    payload = ErrorResponse(
        error_code="research.invalid_request",
        message="request validation failed",
        details={"errors": []},
        trace_id="trace_test_001",
        request_id="req_test_001",
        provider=None,
        degraded=False,
    )
    dumped = payload.model_dump()
    assert dumped["error_code"] == "research.invalid_request"
    assert dumped["trace_id"] == "trace_test_001"
    assert dumped["request_id"] == "req_test_001"
    assert dumped["provider"] is None
    assert dumped["degraded"] is False
