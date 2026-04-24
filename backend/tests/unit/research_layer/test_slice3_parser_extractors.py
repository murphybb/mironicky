from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_layer.extractors.assumption_extractor import AssumptionExtractor
from research_layer.extractors.conflict_extractor import ConflictExtractor
from research_layer.extractors.evidence_extractor import EvidenceExtractor
from research_layer.extractors.failure_extractor import FailureExtractor
from research_layer.extractors.validation_extractor import ValidationExtractor
from research_layer.services.source_parser import ParseFailureError, SourceParser


def test_source_parser_returns_spans_with_workspace_context() -> None:
    parser = SourceParser()
    parsed = parser.parse(
        source_type="paper", content="Claim: A. Method: B. Result: C."
    )

    assert parsed.normalized_content
    assert len(parsed.segments) >= 3
    first = parsed.segments[0]
    assert first.start >= 0
    assert first.end > first.start
    assert first.text


def test_source_parser_splits_chinese_punctuation_into_multiple_segments() -> None:
    parser = SourceParser()
    parsed = parser.parse(
        source_type="paper",
        content=(
            "\u54c1\u724c\u53d7\u635f\u6b63\u5728\u7d2f\u79ef\u3002"
            "\u9700\u8981\u9a8c\u8bc1\u6cbb\u7406\u63aa\u65bd\u662f\u5426\u6709\u6548\uff01"
            "\u8fd8\u8981\u6301\u7eed\u76d1\u6d4b\u4eba\u624d\u6d41\u52a8\uff1f"
        ),
    )

    assert [segment.text for segment in parsed.segments] == [
        "\u54c1\u724c\u53d7\u635f\u6b63\u5728\u7d2f\u79ef\u3002",
        "\u9700\u8981\u9a8c\u8bc1\u6cbb\u7406\u63aa\u65bd\u662f\u5426\u6709\u6548\uff01",
        "\u8fd8\u8981\u6301\u7eed\u76d1\u6d4b\u4eba\u624d\u6d41\u52a8\uff1f",
    ]


def test_source_parser_preserves_structured_block_anchors() -> None:
    parser = SourceParser()
    parsed = parser.parse(
        source_type="paper",
        content="First claim. Supporting evidence.",
        metadata={
            "parser_metadata": {
                "blocks": [
                    {
                        "anchor_id": "p1-b0",
                        "page_number": 1,
                        "block_index": 0,
                        "paragraph_ids": ["p1-b0-par0"],
                        "start": 0,
                        "end": 33,
                        "text": "First claim. Supporting evidence.",
                    }
                ]
            }
        },
    )

    assert [segment.text for segment in parsed.segments] == [
        "First claim.",
        "Supporting evidence.",
    ]
    assert parsed.segments[0].page == 1
    assert parsed.segments[0].block_id == "p1-b0"
    assert parsed.segments[0].paragraph_id == "p1-b0-par0"


def test_source_parser_preserves_raw_structured_table_text() -> None:
    parser = SourceParser()
    parsed = parser.parse(
        source_type="paper",
        content="变量 均值 标准差 品牌态度 4.23 0.86",
        metadata={
            "parser_metadata": {
                "blocks": [
                    {
                        "anchor_id": "p1-b0",
                        "page_number": 1,
                        "block_index": 0,
                        "paragraph_ids": ["p1-b0-par0"],
                        "start": 0,
                        "end": 22,
                        "text": "变量 均值 标准差 品牌态度 4.23 0.86",
                        "raw_text": "变量\t均值\t标准差\n品牌态度\t4.23\t0.86",
                    }
                ]
            }
        },
    )

    assert len(parsed.segments) == 1
    assert parsed.segments[0].artifact_type == "table"
    assert parsed.segments[0].raw_text == "变量\t均值\t标准差\n品牌态度\t4.23\t0.86"


def test_source_parser_raises_parse_failure() -> None:
    parser = SourceParser()
    with pytest.raises(ParseFailureError):
        parser.parse(source_type="note", content="[[PARSE_FAIL]]")


def test_evidence_extractor_returns_structured_candidates() -> None:
    parser = SourceParser()
    parsed = parser.parse(
        source_type="paper",
        content="Claim: retrieval improves quality. Method: add rerank stage.",
    )

    candidates = EvidenceExtractor().extract(parsed)

    assert candidates
    assert all(c.candidate_type == "evidence" for c in candidates)
    assert all(c.source_span.end > c.source_span.start for c in candidates)


def test_all_other_extractors_return_target_candidate_types() -> None:
    parser = SourceParser()
    parsed = parser.parse(
        source_type="failure_record",
        content=(
            "Assumption: cache is warm. Conflict: latency budget exceeded. "
            "Failure: write queue timed out. Validation: run queue chaos test."
        ),
    )

    assumption = AssumptionExtractor().extract(parsed)
    conflict = ConflictExtractor().extract(parsed)
    failure = FailureExtractor().extract(parsed)
    validation = ValidationExtractor().extract(parsed)

    assert assumption and all(c.candidate_type == "assumption" for c in assumption)
    assert conflict and all(c.candidate_type == "conflict" for c in conflict)
    assert failure and all(c.candidate_type == "failure" for c in failure)
    assert validation and all(c.candidate_type == "validation" for c in validation)


def test_fallback_extractors_match_segments_by_target_keywords() -> None:
    parser = SourceParser()
    parsed = parser.parse(
        source_type="paper",
        content=(
            "Claim: rerank improves answer quality. "
            "Assumption: cache remains warm. "
            "Conflict: latency budget is inconsistent. "
            "Failure: queue timed out. "
            "Validation: run replay benchmark."
        ),
    )

    candidates_by_type = {
        "evidence": EvidenceExtractor().build_fallback_candidates(parsed),
        "assumption": AssumptionExtractor().build_fallback_candidates(parsed),
        "conflict": ConflictExtractor().build_fallback_candidates(parsed),
        "failure": FailureExtractor().build_fallback_candidates(parsed),
        "validation": ValidationExtractor().build_fallback_candidates(parsed),
    }

    assert {
        candidate_type: [candidate.text for candidate in candidates]
        for candidate_type, candidates in candidates_by_type.items()
    } == {
        "evidence": ["Claim: rerank improves answer quality."],
        "assumption": ["Assumption: cache remains warm."],
        "conflict": ["Conflict: latency budget is inconsistent."],
        "failure": ["Failure: queue timed out."],
        "validation": ["Validation: run replay benchmark."],
    }
    assert (
        len(
            {
                candidates[0].text
                for candidates in candidates_by_type.values()
                if candidates
            }
        )
        == 5
    )


def test_fallback_extractor_returns_empty_when_no_segment_matches_keywords() -> None:
    parser = SourceParser()
    parsed = parser.parse(
        source_type="note", content="Background: this sentence has no target cue."
    )

    assert ValidationExtractor().build_fallback_candidates(parsed) == []


def test_slice3_prompt_files_are_materialized_for_all_extractors() -> None:
    extractors = (
        EvidenceExtractor(),
        AssumptionExtractor(),
        ConflictExtractor(),
        FailureExtractor(),
        ValidationExtractor(),
    )
    for extractor in extractors:
        assert (
            extractor.prompt_path.exists()
        ), f"missing prompt for {extractor.extractor_name}"


def test_slice3_fixture_covers_required_source_types() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[4]
        / "demo"
        / "research_dev"
        / "fixtures"
        / "slice3_sources.json"
    )
    if not fixture_path.exists():
        pytest.skip("slice3 fixture file is not present in this workspace")
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    source_types = {item["source_type"] for item in payload["sources"]}

    assert {"paper", "note", "failure_record"}.issubset(source_types)
