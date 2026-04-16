from __future__ import annotations

import base64
import io
import zipfile
from datetime import datetime

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.source_import_service import SourceImportError, SourceImportService


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "slice3_source_import.sqlite3"))


def _build_minimal_docx_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as docx_zip:
        docx_zip.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body>"
                "<w:p><w:r><w:t>"
                f"{text}"
                "</w:t></w:r></w:p>"
                "</w:body>"
                "</w:document>"
            ),
        )
    return buffer.getvalue()


def test_source_import_service_manual_text_mode_persists_source(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = SourceImportService(store)

    source = service.import_source(
        workspace_id="ws_manual_01",
        source_type="paper",
        title="Manual Import",
        content="Claim: manual content remains supported.",
        metadata={},
        source_input_mode="manual_text",
        request_id="req_manual_01",
    )

    assert source["workspace_id"] == "ws_manual_01"
    assert source["title"] == "Manual Import"
    assert source["metadata"]["source_input_mode"] == "manual_text"


def test_source_import_service_auto_detects_url_mode(monkeypatch, tmp_path) -> None:
    store = _build_store(tmp_path)
    service = SourceImportService(store)

    monkeypatch.setattr(
        service,
        "_fetch_url_html",
        lambda _url: (
            "<html><head><title>Auto URL Title</title>"
            '<link rel="canonical" href="https://example.org/canonical" /></head>'
            "<body><article>URL extracted body content for import.</article></body></html>"
        ),
    )

    source = service.import_source(
        workspace_id="ws_url_01",
        source_type="paper",
        title=None,
        content=None,
        metadata={},
        source_input_mode="auto",
        source_input="https://example.org/article",
        request_id="req_url_01",
    )

    assert source["title"] == "Auto URL Title"
    assert "URL extracted body content" in source["content"]
    assert source["metadata"]["source_input_mode"] == "url"
    assert source["metadata"]["url"] == "https://example.org/canonical"


def test_source_import_service_parses_docx_local_file(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = SourceImportService(store)
    docx_bytes = _build_minimal_docx_bytes("Docx parsed content for source import.")

    source = service.import_source(
        workspace_id="ws_file_01",
        source_type="paper",
        title=None,
        content=None,
        metadata={},
        source_input_mode="local_file",
        local_file={
            "file_name": "sample.docx",
            "file_content_base64": base64.b64encode(docx_bytes).decode("ascii"),
        },
        request_id="req_file_01",
    )

    assert source["metadata"]["source_input_mode"] == "local_file"
    assert source["metadata"]["local_file_format"] == "docx"
    assert "Docx parsed content" in source["content"]


def test_source_import_service_local_file_does_not_promote_body_doi(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = SourceImportService(store)
    docx_bytes = _build_minimal_docx_bytes(
        "Appendix citation DOI 10.70693/cjst.v2i1.1882 appears in body only."
    )

    source = service.import_source(
        workspace_id="ws_file_doi_01",
        source_type="paper",
        title=None,
        content=None,
        metadata={},
        source_input_mode="local_file",
        local_file={
            "file_name": "sample.docx",
            "file_content_base64": base64.b64encode(docx_bytes).decode("ascii"),
        },
        request_id="req_file_doi_01",
    )

    assert source["metadata"].get("doi") is None


def test_source_import_service_local_file_keeps_supplemental_text(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = SourceImportService(store)
    docx_bytes = _build_minimal_docx_bytes("Docx body content")

    source = service.import_source(
        workspace_id="ws_file_mix_01",
        source_type="note",
        title=None,
        content="manual supplement line",
        metadata={},
        source_input_mode="local_file",
        local_file={
            "file_name": "sample.docx",
            "file_content_base64": base64.b64encode(docx_bytes).decode("ascii"),
        },
        request_id="req_file_mix_01",
    )

    normalized_content = str(source["content"]).lower()
    assert "docx body content" in normalized_content
    assert "manual supplement line" in normalized_content


def test_source_import_service_local_file_respects_explicit_metadata_doi(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = SourceImportService(store)
    docx_bytes = _build_minimal_docx_bytes("Body has no reliable doi")

    source = service.import_source(
        workspace_id="ws_file_doi_02",
        source_type="paper",
        title=None,
        content=None,
        metadata={"doi": "10.1234/example.doi"},
        source_input_mode="local_file",
        local_file={
            "file_name": "sample.docx",
            "file_content_base64": base64.b64encode(docx_bytes).decode("ascii"),
        },
        request_id="req_file_doi_02",
    )

    assert source["metadata"].get("doi") == "10.1234/example.doi"


def test_source_import_service_rejects_unsupported_local_file_format(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = SourceImportService(store)

    with pytest.raises(SourceImportError) as exc_info:
        service.import_source(
            workspace_id="ws_bad_file_01",
            source_type="paper",
            title=None,
            content=None,
            metadata={},
            source_input_mode="local_file",
            local_file={
                "file_name": "notes.txt",
                "file_content_base64": base64.b64encode(b"plain text").decode("ascii"),
            },
            request_id="req_bad_file_01",
        )

    assert exc_info.value.error_code == "research.source_import_unsupported_format"


def test_source_import_service_detects_ranked_publication_year_and_partial_metadata(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    service = SourceImportService(store)
    future_year = datetime.now().year + 2

    source = service.import_source(
        workspace_id="ws_year_01",
        source_type="paper",
        title="Queue Reliability Notes",
        content=(
            f"Archive marker 1899. Baseline in 2017. Main result in 2022 and replication in 2022. "
            f"Future plan in {future_year}. Queue latency and queue retrieval stability stay central."
        ),
        metadata={},
        source_input_mode="manual_text",
        request_id="req_year_01",
    )

    metadata = source["metadata"]
    assert metadata["publication_year"] == 2022
    assert metadata["metadata_completeness_status"] == "partial"
    assert metadata["scholarly_enrichment_required"] is True


def test_source_import_service_cleans_pdf_noise_and_filters_path_tokens_in_topics(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    service = SourceImportService(store)

    source = service.import_source(
        workspace_id="ws_clean_01",
        source_type="paper",
        title="Retrieval Pipeline Cleanup",
        content=(
            "ﬁndings from file://C:/Users/murphy/Desktop/Downloads/report_20250101_final.pdf "
            "stored at C:\\Users\\murphy\\Desktop\\Downloads\\report_20250101_final.pdf "
            "mirror /Users/murphy/Desktop/Downloads/report_20250101_final.html "
            "Page 3 of 12. 2025/11/28 18:16 (1/46). "
            "Retrieval latency and retrieval stability improve with queue controls."
        ),
        metadata={},
        source_input_mode="manual_text",
        request_id="req_clean_01",
    )

    cleaned_content = source["content"].lower()
    assert "file://" not in cleaned_content
    assert "report_20250101_final.pdf" not in cleaned_content
    assert "page 3 of 12" not in cleaned_content
    assert "2025/11/28 18:16" not in cleaned_content
    assert "findings" in cleaned_content

    keywords = {
        str(keyword).lower()
        for cluster in source["metadata"]["topic_clusters"]
        for keyword in cluster.get("keywords", [])
    }
    assert "downloads" not in keywords
    assert "users" not in keywords
    assert "desktop" not in keywords
    assert "pdf" not in keywords
    assert "docx" not in keywords
    assert "html" not in keywords
    assert "retrieval" in keywords


def test_source_import_service_sets_scholarly_enrichment_required_for_missing_fields(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    service = SourceImportService(store)

    complete = service.import_source(
        workspace_id="ws_scholarly_01",
        source_type="paper",
        title="Complete Paper Metadata",
        content="Queue retrieval evidence in 2023 and 2023.",
        metadata={
            "doi": "10.1234/example.doi",
            "authors": ["Researcher A"],
            "venue": "SystemsConf",
        },
        source_input_mode="manual_text",
        request_id="req_scholarly_01",
    )
    missing = service.import_source(
        workspace_id="ws_scholarly_01",
        source_type="paper",
        title="Missing Venue Metadata",
        content="Queue retrieval evidence in 2023 and 2023.",
        metadata={"doi": "10.1234/example.doi", "authors": ["Researcher A"]},
        source_input_mode="manual_text",
        request_id="req_scholarly_02",
    )

    assert complete["metadata"]["scholarly_enrichment_required"] is False
    assert missing["metadata"]["scholarly_enrichment_required"] is True


def test_source_import_service_prioritizes_core_cjk_topics(tmp_path) -> None:
    store = _build_store(tmp_path)
    service = SourceImportService(store)

    source = service.import_source(
        workspace_id="ws_topic_01",
        source_type="paper",
        title="武汉大学品牌声誉深度分析报告",
        content=(
            "本报告围绕品牌、声誉与舆情演化，分析高校治理策略与反馈机制。"
            "品牌建设、舆情响应和高校治理在 2025 年持续出现。"
        ),
        metadata={},
        source_input_mode="manual_text",
        request_id="req_topic_01",
    )

    keywords = {
        str(keyword)
        for cluster in source["metadata"]["topic_clusters"]
        for keyword in cluster.get("keywords", [])
    }
    assert {"品牌", "声誉", "舆情"}.issubset(keywords)
