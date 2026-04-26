from __future__ import annotations

import base64
import asyncio
import io
import zipfile

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.extractors import EvidenceExtractor
from research_layer.services.llm_gateway import ResearchLLMError
from research_layer.services.llm_trace import LLMCallResult
from research_layer.services.source_parser import SourceParser
from research_layer.services.source_chunking_service import SourceChunk
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


def test_extraction_worker_dedupes_llm_hypothesis_paraphrase_without_deterministic_claims(
    tmp_path,
) -> None:
    worker = ExtractionWorker(_build_store(tmp_path))
    llm_claim = {
        "candidate_type": "assumption",
        "semantic_type": "hypothesis",
        "text": "H1:当相对条件一定时,消费者会选择购买与其认知趋近相同的品牌。",
        "source_span": {"start": 0, "end": 31, "text": "H1:当相对条件一定时,消费者会选择购买与其认知趋近相同的品牌。"},
        "quote": "H1:当相对条件一定时,消费者会选择购买与其认知趋近相同的品牌。",
        "extractor_name": "argument_unit_extractor",
    }
    llm_paraphrase = {
        "candidate_type": "conclusion",
        "semantic_type": "claim",
        "text": "Hypothesis H1: Consumers choose brands similar to their cognition under certain conditions",
        "source_span": llm_claim["source_span"],
        "quote": llm_claim["quote"],
        "extractor_name": "argument_unit_extractor",
    }

    deduped = worker._dedupe_candidates([llm_paraphrase, llm_claim])

    assert len(deduped) == 1
    assert deduped[0]["extractor_name"] == "argument_unit_extractor"
    assert str(deduped[0]["text"]).startswith("H1:")


def test_extraction_worker_normalizes_paper_map_payload(tmp_path) -> None:
    worker = ExtractionWorker(_build_store(tmp_path))

    memo = worker._normalize_document_reading_memo(
        {
            "document_summary": "AIFS paper summary",
            "document_type": "academic_paper",
            "domain_profile": ["weather_forecasting"],
            "research_questions": [
                {
                    "quote": "Can a data-driven forecasting system match IFS?",
                    "reason": "central question",
                    "section": "Introduction",
                }
            ],
            "method_chain": [
                {
                    "quote": "AIFS uses an encoder, processor, and decoder.",
                    "reason": "architecture",
                }
            ],
            "results_or_findings": [
                {"quote": "AIFS outperforms IFS for several variables.", "reason": "result"}
            ],
            "coverage_warnings": ["tables are not fully represented"],
        }
    )

    required_keys = {
        "document_summary",
        "document_type",
        "research_questions",
        "main_contributions",
        "hypotheses_or_claims",
        "method_chain",
        "data_or_corpus",
        "experiments_or_validation",
        "results_or_findings",
        "limitations_or_open_questions",
        "artifact_index",
        "route_seed_candidates",
        "coverage_warnings",
    }

    assert required_keys.issubset(memo.keys())
    assert memo["document_type"] == "academic_paper"
    assert memo["research_questions"][0]["section"] == "Introduction"
    assert memo["method_chain"][0]["quote"].startswith("AIFS uses")
    assert memo["coverage_warnings"] == ["tables are not fully represented"]


def test_extraction_worker_persists_paper_map_as_source_artifact(tmp_path) -> None:
    store = _build_store(tmp_path)
    worker = ExtractionWorker(store)
    parsed = SourceParser().parse(
        source_type="paper",
        content="AIFS uses a graph neural network architecture.",
        metadata={},
    )
    store.replace_source_artifacts(
        workspace_id="ws_paper_map_artifact",
        source_id="src_paper_map",
        artifacts=worker._build_source_artifacts(
            workspace_id="ws_paper_map_artifact",
            source_id="src_paper_map",
            parsed=parsed,
        ),
    )

    worker._persist_paper_map_artifact(
        workspace_id="ws_paper_map_artifact",
        source_id="src_paper_map",
        document_reading_memo={
            "document_summary": "AIFS paper",
            "document_type": "technical_report",
        },
    )

    artifacts = store.list_source_artifacts(
        workspace_id="ws_paper_map_artifact", source_id="src_paper_map"
    )
    paper_map_artifacts = [
        artifact for artifact in artifacts if artifact["artifact_type"] == "paper_map"
    ]

    assert len(paper_map_artifacts) == 1
    assert paper_map_artifacts[0]["anchor_id"] == "paper_map"
    assert paper_map_artifacts[0]["metadata"]["schema"] == "paper_map_v1"
    assert paper_map_artifacts[0]["metadata"]["prompt_name"] == "extraction_document_reader"
    assert "AIFS paper" in paper_map_artifacts[0]["content"]


def test_extraction_worker_builds_source_grounded_paper_map_focus_chunk(tmp_path) -> None:
    worker = ExtractionWorker(_build_store(tmp_path))
    parsed = SourceParser().parse(
        source_type="paper",
        content=(
            "H1:当相对条件一定时,消费者会选择购买与其认知趋近相同的品牌。\n"
            "H2:社会主流向善一致性中介于文化认知与品牌态度之间。\n"
            "实验二为问卷调查法，通过对中介作用的考察来进一步揭示机制。"
        ),
        metadata={},
    )

    focus_chunk = worker._build_paper_map_focus_chunk(
        source_id="src_focus",
        parsed=parsed,
        document_reading_memo={
            "hypotheses_or_claims": [
                {
                    "quote": "H1:当相对条件一定时,消费者会选择购买与其认知趋近相同的品牌。",
                    "reason": "central hypothesis",
                },
                {
                    "quote": "H4:这句话不在原文里。",
                    "reason": "hallucinated hypothesis",
                },
            ],
            "experiments_or_validation": [
                {
                    "quote": "实验二为问卷调查法，通过对中介作用的考察来进一步揭示机制。",
                    "reason": "validation design",
                }
            ],
        },
        chunk_index=7,
    )

    assert focus_chunk is not None
    assert focus_chunk.chunk_id == "src_focus:paper_map_focus"
    assert focus_chunk.chunk_index == 7
    assert focus_chunk.section_hint == "paper_map_focus"
    assert "H1:当相对条件一定时" in focus_chunk.text
    assert "实验二为问卷调查法" in focus_chunk.text
    assert "H4:这句话不在原文里" not in focus_chunk.text


@pytest.mark.asyncio
async def test_extraction_worker_appends_paper_map_focus_chunk_to_extraction_plan(
    monkeypatch, tmp_path
) -> None:
    store = _build_store(tmp_path)
    import_service = SourceImportService(store)
    source = import_service.import_source(
        workspace_id="ws_focus_plan",
        source_type="paper",
        title="focus paper",
        content=(
            "H1:当相对条件一定时,消费者会选择购买与其认知趋近相同的品牌。\n"
            "普通段落提供背景材料。"
        ),
        metadata={},
        request_id="req_focus_plan",
    )
    job = store.create_job(
        job_type="source_extract",
        workspace_id="ws_focus_plan",
        request_id="req_focus_plan",
    )
    worker = ExtractionWorker(store)

    async def fake_document_reader(**kwargs):
        return {
            "hypotheses_or_claims": [
                {
                    "quote": "H1:当相对条件一定时,消费者会选择购买与其认知趋近相同的品牌。",
                    "reason": "central hypothesis",
                }
            ]
        }

    captured_chunks: list[SourceChunk] = []

    async def fake_extract_chunks_for_plan(**kwargs):
        captured_chunks.extend(kwargs["chunks"])
        return []

    monkeypatch.setattr(worker, "_build_document_reading_memo", fake_document_reader)
    monkeypatch.setattr(worker, "_extract_chunks_for_plan", fake_extract_chunks_for_plan)

    result = await worker.run(
        request_id="req_focus_plan",
        job_id=str(job["job_id"]),
        workspace_id="ws_focus_plan",
        source_id=str(source["source_id"]),
    )

    assert result["status"] == "succeeded"
    assert captured_chunks
    assert captured_chunks[-1].chunk_id.endswith(":paper_map_focus")
    assert captured_chunks[-1].section_hint == "paper_map_focus"


def test_extraction_worker_document_reader_chunk_samples_whole_document(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("RESEARCH_SOURCE_EXTRACT_MAX_INPUT_CHARS", "320")
    monkeypatch.setenv("RESEARCH_SOURCE_EXTRACT_MAX_INPUT_SEGMENTS", "6")
    worker = ExtractionWorker(_build_store(tmp_path))
    content = " ".join(
        [
            "Opening sentence describes the paper goal.",
            "Opening context explains the study background.",
            *[f"Filler sentence {index} repeats background." for index in range(20)],
            "H1: The tested hypothesis links cognition to brand attitude.",
            *[f"More filler sentence {index}." for index in range(20)],
            "Conclusion: The final finding reports the mediation chain.",
        ]
    )
    parsed = SourceParser().parse(source_type="paper", content=content, metadata={})

    prompt_chunk = worker._build_document_reader_prompt_chunk(parsed)

    assert "Opening sentence describes the paper goal" in prompt_chunk
    assert "H1: The tested hypothesis" in prompt_chunk
    assert "Conclusion: The final finding" in prompt_chunk


def test_extraction_worker_default_chunking_does_not_collapse_long_paper(
    tmp_path,
) -> None:
    worker = ExtractionWorker(_build_store(tmp_path))
    content_blocks = [
        {
            "text": f"Section {index}. " + ("This paragraph describes one paper section. " * 140),
            "start": index * 5000,
            "page": index + 1,
            "anchor_id": f"p{index + 1}-b0",
        }
        for index in range(6)
    ]
    parsed = SourceParser().parse(
        source_type="paper",
        content=" ".join(str(block["text"]) for block in content_blocks),
        metadata={"parser_metadata": {"blocks": content_blocks}},
    )

    chunk_plan = worker._chunking.plan(source_id="src_long_paper", parsed=parsed)

    assert len(chunk_plan.chunks) > 1
    assert max(len(chunk.text) for chunk in chunk_plan.chunks) <= 10000


@pytest.mark.asyncio
async def test_extraction_worker_processes_chunks_concurrently(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("RESEARCH_SOURCE_EXTRACT_CHUNK_CONCURRENCY", "3")
    worker = ExtractionWorker(_build_store(tmp_path))
    active = 0
    max_active = 0

    async def fake_extract_argument_units_for_chunk(**kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        chunk = kwargs["chunk"]
        return (
            [],
            [
                {
                    "candidate_type": "evidence",
                    "text": f"candidate {chunk.chunk_index}",
                    "source_span": {"start": 0, "end": 1, "text": "x"},
                }
            ],
            None,
        )

    monkeypatch.setattr(
        worker,
        "_extract_argument_units_for_chunk",
        fake_extract_argument_units_for_chunk,
    )
    chunks = [
        SourceChunk(
            chunk_id=f"src:chunk:{index}",
            chunk_index=index,
            section_hint="full",
            start=index,
            end=index + 1,
            text=f"chunk {index}",
            chunk_hash=f"hash{index}",
        )
        for index in range(5)
    ]

    results = await worker._extract_chunks_for_plan(
        request_id="req_concurrent_chunks",
        job_id="job_concurrent_chunks",
        workspace_id="ws_concurrent_chunks",
        source={"source_id": "src_concurrent_chunks"},
        parsed=SourceParser().parse(source_type="paper", content="x. y.", metadata={}),
        batch_id="batch_concurrent_chunks",
        chunks=chunks,
        chunk_count=len(chunks),
        document_reading_memo={},
        failure_mode=None,
        backend=None,
        model=None,
    )

    assert max_active > 1
    assert len(results) == 5
    assert [result["chunk_index"] for result in results] == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_extraction_worker_chunk_cache_is_scoped_by_paper_map(tmp_path) -> None:
    store = _build_store(tmp_path)
    worker = ExtractionWorker(store)
    old_paper_map = {"document_summary": "old PaperMap"}
    new_paper_map = {"document_summary": "new PaperMap"}
    parsed = SourceParser().parse(
        source_type="paper",
        content="fresh claim. cached claim.",
        metadata={},
    )
    chunk = SourceChunk(
        chunk_id="src_cache:chunk:0",
        chunk_index=0,
        section_hint="abstract",
        start=0,
        end=len(parsed.normalized_content),
        text=parsed.normalized_content,
        chunk_hash="same_chunk_hash",
    )
    store.upsert_source_chunk_cache(
        workspace_id="ws_cache_scope",
        source_id="src_cache",
        chunk_hash=chunk.chunk_hash,
        cache_key=(
            "candidate:argument_unit_extractor:v10_paper_map_units:"
            f"{worker._paper_map_cache_hash(old_paper_map)}"
        ),
        payload={
            "paper_map_hash": worker._paper_map_cache_hash(old_paper_map),
            "units": [{"text": "cached claim"}],
            "candidates": [
                {
                    "candidate_type": "evidence",
                    "text": "cached claim",
                    "source_span": {"start": 13, "end": 25, "text": "cached claim"},
                }
            ],
        },
    )

    class _FreshGateway:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke_text(self, **kwargs: object) -> LLMCallResult:
            self.calls += 1
            return LLMCallResult(
                provider_backend="unit_test_backend",
                provider_model="unit_test_model",
                request_id=str(kwargs["request_id"]),
                llm_response_id="resp_cache_scope",
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                raw_text=(
                    '{"units":[{"unit_id":"unit_fresh","candidate_type":"evidence",'
                    '"semantic_type":"result","text":"fresh claim",'
                    '"quote":"fresh claim","confidence_score":0.9}]}'
                ),
                parsed_json={
                    "units": [
                        {
                            "unit_id": "unit_fresh",
                            "candidate_type": "evidence",
                            "semantic_type": "result",
                            "text": "fresh claim",
                            "quote": "fresh claim",
                            "confidence_score": 0.9,
                        }
                    ]
                },
                fallback_used=False,
                degraded=False,
                degraded_reason=None,
            )

    gateway = _FreshGateway()
    worker._gateway = gateway

    _, candidates, trace = await worker._extract_argument_units_for_chunk(
        request_id="req_cache_scope",
        workspace_id="ws_cache_scope",
        source={"source_id": "src_cache", "title": "paper", "source_type": "paper"},
        parsed=parsed,
        chunk=chunk,
        document_reading_memo=new_paper_map,
        failure_mode=None,
        backend=None,
        model=None,
    )

    assert gateway.calls == 1
    assert trace is not None
    assert [candidate["text"] for candidate in candidates] == ["fresh claim"]


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



