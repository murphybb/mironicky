from __future__ import annotations

import base64
import io
import zipfile

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.extractors import EvidenceExtractor
from research_layer.services.llm_gateway import ResearchLLMError
from research_layer.services.llm_trace import LLMCallResult
from research_layer.services.source_parser import SourceParser
from research_layer.services.source_import_service import SourceImportService
from research_layer.workers.extraction_worker import ExtractionWorker


def _build_store(tmp_path) -> ResearchApiStateStore:
    db_path = tmp_path / "slice3_extraction_worker.sqlite3"
    return ResearchApiStateStore(db_path=str(db_path))


def test_extraction_worker_default_llm_timeout_is_five_minutes(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("RESEARCH_SOURCE_EXTRACT_LLM_TIMEOUT_SECONDS", raising=False)

    worker = ExtractionWorker(_build_store(tmp_path))

    assert worker._resolve_llm_timeout_seconds() == 300.0


def test_extraction_worker_default_output_budget_handles_prompt_b_json(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("RESEARCH_SOURCE_EXTRACT_MAX_OUTPUT_TOKENS", raising=False)

    worker = ExtractionWorker(_build_store(tmp_path))

    assert worker._resolve_output_max_tokens() == 12000


def _build_long_source_content() -> str:
    return " ".join(f"Sentence {index:04d}." for index in range(32))


def _build_minimal_docx_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as docx_zip:
        docx_zip.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body>"
                f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
                "</w:body>"
                "</w:document>"
            ),
        )
    return buffer.getvalue()


def test_extraction_worker_resolves_pdf_whitespace_span(tmp_path) -> None:
    worker = ExtractionWorker(_build_store(tmp_path))
    parsed = SourceParser().parse(
        source_type="paper",
        content=(
            "H2:社会主流向善一致性中介于文化认知与品牌态度 \n"
            "之间,有积极的影响。数据显示,95.6% 属于积极品牌态度的范畴。"
        ),
        metadata={},
    )

    start, end, text = worker._resolve_source_span(
        parsed=parsed,
        primary_query="H2:社会主流向善一致性中介于文化认知与品牌态度之间,有积极的影响。",
        secondary_query=None,
    )

    assert start >= 0
    assert end > start
    assert "品牌态度" in text


def test_extraction_worker_builds_traceable_source_artifacts(tmp_path) -> None:
    worker = ExtractionWorker(_build_store(tmp_path))
    parsed = SourceParser().parse(
        source_type="paper",
        content="变量\t均值\t标准差\n品牌态度\t4.23\t0.86\n差序格局\t3.91\t0.72",
        metadata={
            "parser_metadata": {
                "blocks": [
                    {
                        "anchor_id": "p1-b0",
                        "page_number": 1,
                        "block_index": 0,
                        "paragraph_ids": ["p1-b0-par0"],
                        "start": 0,
                        "end": 42,
                        "text": "变量\t均值\t标准差\n品牌态度\t4.23\t0.86\n差序格局\t3.91\t0.72",
                    }
                ]
            }
        },
    )

    artifacts = worker._build_source_artifacts(
        workspace_id="ws_artifact", source_id="src_paper", parsed=parsed
    )

    assert len(artifacts) == 1
    assert artifacts[0]["artifact_id"] == "art_src_paper_p1-b0"
    assert artifacts[0]["artifact_type"] == "table"
    assert artifacts[0]["locator"]["page"] == 1
    assert artifacts[0]["locator"]["block_id"] == "p1-b0"
    assert artifacts[0]["content"] == "变量\t均值\t标准差\n品牌态度\t4.23\t0.86\n差序格局\t3.91\t0.72"
    assert artifacts[0]["metadata"]["structure"]["headers"] == ["变量", "均值", "标准差"]
    assert artifacts[0]["metadata"]["structure"]["row_count"] == 2
    assert artifacts[0]["metadata"]["structure"]["rows"][0]["mapping"]["变量"] == "品牌态度"


def test_extraction_worker_classifies_figure_formula_and_code_artifacts(tmp_path) -> None:
    worker = ExtractionWorker(_build_store(tmp_path))

    assert worker._classify_source_artifact("Figure 2. Accuracy comparison across models") == "figure"
    assert worker._classify_source_artifact("x_{t+1}=x_t-η∇L(x_t)") == "formula"
    assert (
        worker._classify_source_artifact("def train():\n    return loss\nfor step in range(10):")
        == "code"
    )


def test_extraction_worker_builds_chunk_artifact_profile(tmp_path) -> None:
    worker = ExtractionWorker(_build_store(tmp_path))

    profile = worker._build_chunk_artifact_profile(
        parsed=SourceParser().parse(
            source_type="paper",
            content="Figure 2. Accuracy rises. Background text.",
            metadata={
                "parser_metadata": {
                    "blocks": [
                        {
                            "anchor_id": "p1-b0",
                            "page_number": 1,
                            "block_index": 0,
                            "paragraph_ids": ["p1-b0-par0"],
                            "start": 0,
                            "end": 25,
                            "text": "Figure 2. Accuracy rises.",
                            "raw_text": "Figure 2. Accuracy rises.",
                        },
                        {
                            "anchor_id": "p1-b1",
                            "page_number": 1,
                            "block_index": 1,
                            "paragraph_ids": ["p1-b1-par0"],
                            "start": 26,
                            "end": 42,
                            "text": "Background text.",
                            "raw_text": "Background text.",
                        },
                    ]
                }
            },
        ),
        chunk=type(
            "ChunkStub",
            (),
            {"start": 0, "end": 42, "section_hint": "full"},
        )(),
        anchor_refs=[
            {"artifact_type": "figure"},
            {"artifact_type": "figure"},
            {"artifact_type": "text"},
        ],
    )

    assert profile["dominant_artifact_type"] == "figure"
    assert profile["extraction_focus"] == "figure"
    assert profile["artifact_counts"] == {"figure": 2, "text": 1}
    assert profile["artifacts"][0]["structure"]["label"] == "Figure 2."


def test_extraction_worker_handles_ragged_table_rows(tmp_path) -> None:
    worker = ExtractionWorker(_build_store(tmp_path))

    structure = worker._extract_table_structure(
        "变量\t均值\n品牌态度\t4.23\t0.86\n差序格局\t3.91"
    )

    assert structure["column_count"] == 3
    assert structure["headers"] == ["变量", "均值", "col_3"]
    assert structure["rows"][0]["mapping"]["col_3"] == "0.86"
    assert structure["rows"][1]["mapping"]["col_3"] == ""


@pytest.mark.asyncio
async def test_extraction_worker_limits_prompt_window_and_output_tokens(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("RESEARCH_SOURCE_EXTRACT_MAX_INPUT_CHARS", "200")
    monkeypatch.setenv("RESEARCH_SOURCE_EXTRACT_MAX_INPUT_SEGMENTS", "3")
    monkeypatch.setenv("RESEARCH_SOURCE_CHUNK_MAX_CHARS", "200")
    monkeypatch.setenv("RESEARCH_SOURCE_CHUNK_MAX_SEGMENTS", "3")
    monkeypatch.setenv("RESEARCH_SOURCE_EXTRACT_MAX_OUTPUT_TOKENS", "77")

    store = _build_store(tmp_path)
    import_service = SourceImportService(store)
    source = import_service.import_source(
        workspace_id="ws_slice3_extract_limit",
        source_type="paper",
        title="long docx import",
        content=None,
        metadata={},
        source_input_mode="local_file",
        local_file={
            "file_name": "oversized.docx",
            "file_content_base64": base64.b64encode(
                _build_minimal_docx_bytes(_build_long_source_content())
            ).decode("ascii"),
        },
        request_id="req_slice3_extract_limit",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id="ws_slice3_extract_limit",
        request_id="req_slice3_extract_limit",
    )

    worker = ExtractionWorker(store)
    worker._extractors = (EvidenceExtractor(),)
    captured: dict[str, object] = {}

    class _FakeGateway:
        async def invoke_text(self, **kwargs: object) -> LLMCallResult:
            prompt_name = str(kwargs.get("prompt_name") or "")
            raw_text = (
                '{"document_summary":"short memo","domain_profile":["test"],'
                '"structure_hints":{"concepts":[],"claims_or_hypotheses":[],'
                '"methods_or_measurements":[],"results_or_evidence":[],'
                '"conditions_or_limits":[],"relation_cues":[]}}'
            )
            if prompt_name == "argument_unit_extraction" and not captured:
                captured.update(kwargs)
            if prompt_name == "argument_unit_extraction":
                raw_text = '{"units":[]}'
            if prompt_name.startswith("argument_relation"):
                raw_text = '{"relations":[]}'
            return LLMCallResult(
                provider_backend="unit_test_backend",
                provider_model="unit_test_model",
                request_id=str(kwargs["request_id"]),
                llm_response_id="resp_slice3_extract_limit_text",
                usage={"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
                raw_text=raw_text,
                parsed_json=None,
                fallback_used=False,
                degraded=False,
                degraded_reason=None,
            )

        async def invoke_json(self, **kwargs: object) -> LLMCallResult:
            return LLMCallResult(
                provider_backend="unit_test_backend",
                provider_model="unit_test_model",
                request_id=str(kwargs["request_id"]),
                llm_response_id="resp_slice3_extract_limit",
                usage={"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
                raw_text='{"units":[]}',
                parsed_json={"units": []},
                fallback_used=False,
                degraded=False,
                degraded_reason=None,
            )

    worker._gateway = _FakeGateway()

    result = await worker.run(
        request_id="req_slice3_extract_limit",
        job_id=str(job["job_id"]),
        workspace_id="ws_slice3_extract_limit",
        source_id=str(source["source_id"]),
    )

    assert result["status"] == "succeeded"
    assert captured["max_tokens"] == 77
    messages = captured["messages"]
    serialized_messages = "\n".join(str(message.content) for message in messages)
    assert "Sentence 0000." in serialized_messages
    assert "Sentence 0001." in serialized_messages
    assert "Sentence 0002." in serialized_messages
    assert "Sentence 0003." not in serialized_messages


class _InvalidJsonGateway:
    async def invoke_text(self, **kwargs: object) -> LLMCallResult:
        raise ResearchLLMError(
            status_code=502,
            error_code="research.llm_invalid_output",
            message="invalid extraction JSON",
            details={"provider_message": "not-json"},
        )

    async def invoke_json(self, **kwargs: object) -> LLMCallResult:
        raise ResearchLLMError(
            status_code=502,
            error_code="research.llm_invalid_output",
            message="invalid extraction JSON",
            details={"provider_message": "not-json"},
        )


@pytest.mark.asyncio
async def test_extraction_worker_adds_minimal_candidate_when_allowed_fallback_is_empty(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    import_service = SourceImportService(store)
    source_text = "Alpha beta gamma keeps the protocol sparse."
    source = import_service.import_source(
        workspace_id="ws_slice3_empty_fallback",
        source_type="paper",
        title="paper without extractor keywords",
        content=source_text,
        metadata={},
        request_id="req_slice3_empty_fallback",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id="ws_slice3_empty_fallback",
        request_id="req_slice3_empty_fallback",
    )

    worker = ExtractionWorker(store)
    worker._extractors = (EvidenceExtractor(),)
    worker._gateway = _InvalidJsonGateway()

    result = await worker.run(
        request_id="req_slice3_empty_fallback",
        job_id=str(job["job_id"]),
        workspace_id="ws_slice3_empty_fallback",
        source_id=str(source["source_id"]),
        allow_fallback=True,
    )

    assert result["status"] == "succeeded"
    batch = store.get_candidate_batch(str(result["candidate_batch_id"]))
    assert batch is not None
    assert batch["candidate_ids"]
    assert batch["fallback_used"] is True
    assert batch["degraded"] is True
    assert batch["degraded_reason"] == "research.llm_invalid_output"
    assert batch["partial_failure_count"] == 1

    candidate = store.get_candidate(str(batch["candidate_ids"][0]))
    assert candidate is not None
    assert candidate["candidate_type"] == "evidence"
    assert candidate["text"] == source_text
    assert candidate["source_span"] == {"start": 0, "end": len(source_text), "text": source_text}
    assert candidate["extractor_name"] == "deterministic_fallback"
    assert candidate["provider_model"] == "fallback_parser"
    assert candidate["request_id"] == "req_slice3_empty_fallback"
    assert candidate["llm_response_id"] == "req_slice3_empty_fallback"
    assert candidate["fallback_used"] is True
    assert candidate["degraded"] is True
    assert candidate["degraded_reason"] == "research.llm_invalid_output"


@pytest.mark.asyncio
async def test_extraction_worker_prefers_semantic_segment_for_minimal_fallback(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    import_service = SourceImportService(store)
    source_text = (
        "1.\n2.\n"
        "Wuhan University reputation analysis indicates public-opinion risk accumulation "
        "and requires governance improvement."
    )
    source = import_service.import_source(
        workspace_id="ws_slice3_semantic_fallback",
        source_type="paper",
        title="paper with short list prefix",
        content=source_text,
        metadata={},
        request_id="req_slice3_semantic_fallback",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id="ws_slice3_semantic_fallback",
        request_id="req_slice3_semantic_fallback",
    )

    worker = ExtractionWorker(store)
    worker._extractors = (EvidenceExtractor(),)
    worker._gateway = _InvalidJsonGateway()

    result = await worker.run(
        request_id="req_slice3_semantic_fallback",
        job_id=str(job["job_id"]),
        workspace_id="ws_slice3_semantic_fallback",
        source_id=str(source["source_id"]),
        allow_fallback=True,
    )

    assert result["status"] == "succeeded"
    batch = store.get_candidate_batch(str(result["candidate_batch_id"]))
    assert batch is not None and batch["candidate_ids"]
    candidate = store.get_candidate(str(batch["candidate_ids"][0]))
    assert candidate is not None
    assert len(str(candidate["text"])) >= 20
    assert "Wuhan University reputation analysis" in str(candidate["text"])


@pytest.mark.asyncio
async def test_extraction_worker_uses_explicit_degraded_text_when_all_segments_are_low_value(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    import_service = SourceImportService(store)
    source_text = "1.\n2.\n3.\n4."
    source = import_service.import_source(
        workspace_id="ws_slice3_low_value_fallback",
        source_type="paper",
        title="paper with only list markers",
        content=source_text,
        metadata={},
        request_id="req_slice3_low_value_fallback",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id="ws_slice3_low_value_fallback",
        request_id="req_slice3_low_value_fallback",
    )

    worker = ExtractionWorker(store)
    worker._extractors = (EvidenceExtractor(),)
    worker._gateway = _InvalidJsonGateway()

    result = await worker.run(
        request_id="req_slice3_low_value_fallback",
        job_id=str(job["job_id"]),
        workspace_id="ws_slice3_low_value_fallback",
        source_id=str(source["source_id"]),
        allow_fallback=True,
    )

    assert result["status"] == "succeeded"
    batch = store.get_candidate_batch(str(result["candidate_batch_id"]))
    assert batch is not None and batch["candidate_ids"]
    candidate = store.get_candidate(str(batch["candidate_ids"][0]))
    assert candidate is not None
    assert str(candidate["text"]).startswith("auto-degraded candidate:")
    assert candidate["source_span"]["text"] == "1."


@pytest.mark.asyncio
async def test_extraction_worker_supplements_fallback_candidates_to_reach_chain_floor(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    import_service = SourceImportService(store)
    source_text = (
        "Brand recovery usually needs sustained governance reform over a long window.\n"
        "Validation should monitor talent flow and academic reputation indicators continuously.\n"
        "Past campus traffic incidents triggered prolonged dispute and public-opinion rebound, "
        "which amplifies execution risk."
    )
    source = import_service.import_source(
        workspace_id="ws_slice3_supplemental_fallback",
        source_type="paper",
        title="paper needing supplemental fallback",
        content=source_text,
        metadata={},
        request_id="req_slice3_supplemental_fallback",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id="ws_slice3_supplemental_fallback",
        request_id="req_slice3_supplemental_fallback",
    )

    worker = ExtractionWorker(store)
    worker._extractors = (EvidenceExtractor(),)
    worker._gateway = _InvalidJsonGateway()

    result = await worker.run(
        request_id="req_slice3_supplemental_fallback",
        job_id=str(job["job_id"]),
        workspace_id="ws_slice3_supplemental_fallback",
        source_id=str(source["source_id"]),
        allow_fallback=True,
    )

    assert result["status"] == "succeeded"
    batch = store.get_candidate_batch(str(result["candidate_batch_id"]))
    assert batch is not None
    candidate_ids = list(batch["candidate_ids"])
    assert len(candidate_ids) >= 2

    candidates = [store.get_candidate(str(candidate_id)) for candidate_id in candidate_ids]
    candidates = [candidate for candidate in candidates if candidate is not None]
    extractor_names = {str(candidate["extractor_name"]) for candidate in candidates}

    assert any(name.startswith("deterministic_supplemental_fallback_") for name in extractor_names)


@pytest.mark.asyncio
async def test_extraction_worker_fails_invalid_json_when_fallback_not_allowed(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    import_service = SourceImportService(store)
    source = import_service.import_source(
        workspace_id="ws_slice3_no_fallback",
        source_type="paper",
        title="paper without fallback",
        content="Alpha beta gamma keeps the protocol sparse.",
        metadata={},
        request_id="req_slice3_no_fallback",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id="ws_slice3_no_fallback",
        request_id="req_slice3_no_fallback",
    )

    worker = ExtractionWorker(store)
    worker._extractors = (EvidenceExtractor(),)
    worker._gateway = _InvalidJsonGateway()

    result = await worker.run(
        request_id="req_slice3_no_fallback",
        job_id=str(job["job_id"]),
        workspace_id="ws_slice3_no_fallback",
        source_id=str(source["source_id"]),
        allow_fallback=False,
    )

    assert result["status"] == "failed"
    assert result["error"]["error_code"] == "research.llm_invalid_output"
    assert store.list_candidates(
        workspace_id="ws_slice3_no_fallback",
        source_id=str(source["source_id"]),
        candidate_type=None,
    ) == []
    persisted_job = store.get_job(str(job["job_id"]))
    assert persisted_job is not None
    assert persisted_job["status"] == "failed"
    assert persisted_job["error"]["error_code"] == "research.llm_invalid_output"



