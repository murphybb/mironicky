from __future__ import annotations

import base64
import binascii
import io
import re
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from collections import Counter as CollectionsCounter, defaultdict
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from xml.etree import ElementTree

from prometheus_client import Counter, Histogram

from core.observation.logger import get_logger
from core.observation.metrics.registry import get_metrics_registry
from research_layer.api.controllers._state_store import ResearchApiStateStore

_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_FILE_URL_RE = re.compile(r"\bfile://[^\s]+", re.IGNORECASE)
_LOCAL_FILE_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|(?<!:)/)(?:[^\\/\s]+[\\/])+[^\\/\s]+\.(?:pdf|docx?|html?)\b",
    re.IGNORECASE,
)
_FILE_NAME_NOISE_RE = re.compile(r"\b[^\\/\s]+\.(?:pdf|docx?|html?)\b", re.IGNORECASE)
_PAGE_FOOTER_RE = re.compile(r"\bpage\s+\d+\s*(?:of\s+\d+)?\b", re.IGNORECASE)
_PAGE_INDEX_RE = re.compile(r"\(\s*\d+\s*/\s*\d+\s*\)")
_DATETIME_FOOTER_RE = re.compile(
    r"\b20\d{2}[/-]\d{1,2}[/-]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?\b"
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_CANONICAL_RE = re.compile(
    r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\'](.*?)["\'][^>]*>',
    re.IGNORECASE | re.DOTALL,
)
_SUPPORTED_LOCAL_FILE_EXTENSIONS = {".pdf", ".docx"}
_TOPIC_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_TOPIC_CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,8}")
_TOPIC_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?;；\n]+")
_TOPIC_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "if",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "this",
    "to",
    "was",
    "we",
    "when",
    "which",
    "with",
    "研究",
    "以及",
    "我们",
    "你们",
    "他们",
    "一个",
    "一种",
    "进行",
    "相关",
    "问题",
    "通过",
}
_TOPIC_CJK_STOPWORDS = {
    "然而",
    "因此",
    "以及",
    "通过",
    "相关",
    "问题",
    "研究",
    "报告",
    "进行",
    "本文",
    "本报告",
    "我们",
    "你们",
    "他们",
}
logger = get_logger(__name__)
_TOPIC_NOISE_TOKENS = {
    "downloads",
    "users",
    "desktop",
    "html",
    "pdf",
    "docx",
    "guohangjiang",
    "nal_report",
}
_TOPIC_PRIORITY_TERMS = (
    "品牌",
    "声誉",
    "舆情",
    "高校治理",
    "高校",
    "治理",
)
_TOPIC_PATH_NOISE_TOKEN_RE = re.compile(r"^(?=.*\d{3,})(?=.*_)[a-z0-9_]+$")

_source_import_total = Counter(
    name="research_source_import_total",
    documentation="Total source import attempts by mode and outcome",
    labelnames=["source_input_mode", "outcome"],
    namespace="evermemos",
    registry=get_metrics_registry(),
)
_source_import_duration_seconds = Histogram(
    name="research_source_import_duration_seconds",
    documentation="Source import operation duration in seconds",
    labelnames=["source_input_mode", "outcome"],
    namespace="evermemos",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0),
    registry=get_metrics_registry(),
)
_source_import_payload_bytes = Histogram(
    name="research_source_import_payload_bytes",
    documentation="Estimated source import payload size in bytes",
    labelnames=["source_input_mode"],
    namespace="evermemos",
    buckets=(128, 512, 1024, 4096, 16384, 65536, 262144, 1048576, 5242880, 10485760),
    registry=get_metrics_registry(),
)


class SourceImportError(RuntimeError):
    def __init__(
        self,
        *,
        error_code: str,
        message: str,
        details: dict[str, object] | None = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        self.status_code = status_code


@dataclass(frozen=True)
class _ResolvedSourceImport:
    source_input_mode: str
    title: str
    content: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class StructuredPdfBlock:
    page_number: int
    block_index: int
    text: str
    anchor_id: str
    start: int
    end: int
    paragraph_ids: tuple[str, ...]


@dataclass(frozen=True)
class StructuredPdfDocument:
    parser: str
    pages: int
    text: str
    chars: int
    blocks: tuple[StructuredPdfBlock, ...]


class SourceImportService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def import_source(
        self,
        *,
        workspace_id: str,
        source_type: str,
        title: str | None,
        content: str | None,
        metadata: dict[str, object],
        source_input_mode: str = "auto",
        source_input: str | None = None,
        source_url: str | None = None,
        local_file: dict[str, object] | None = None,
        request_id: str,
    ) -> dict[str, object]:
        started_at = time.perf_counter()
        mode_hint = (source_input_mode or "auto").strip().lower() or "auto"
        payload_bytes = self._estimate_payload_bytes(
            source_input_mode=mode_hint,
            source_input=source_input,
            source_url=source_url,
            content=content,
            local_file=local_file,
        )
        logger.info(
            "research.source_import.start req=%s workspace=%s source_type=%s mode=%s payload_bytes=%d",
            request_id,
            workspace_id,
            source_type,
            mode_hint,
            payload_bytes,
        )
        _source_import_payload_bytes.labels(source_input_mode=mode_hint).observe(
            payload_bytes
        )

        try:
            resolved = self._resolve_source_payload(
                source_type=source_type,
                title=title,
                content=content,
                metadata=metadata,
                source_input_mode=source_input_mode,
                source_input=source_input,
                source_url=source_url,
                local_file=local_file,
            )
            source_id = self._store.gen_id("src")
            self._store.emit_event(
                event_name="source_import_started",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                source_id=source_id,
                component="source_import_service",
                step="import",
                status="started",
                refs={
                    "source_type": source_type,
                    "source_id": source_id,
                    "source_input_mode": resolved.source_input_mode,
                },
            )
            source = self._store.create_source(
                source_id=source_id,
                workspace_id=workspace_id,
                source_type=source_type,
                title=resolved.title,
                content=resolved.content,
                metadata=resolved.metadata,
                import_request_id=request_id,
            )
            self._store.emit_event(
                event_name="source_import_completed",
                request_id=request_id,
                job_id=None,
                workspace_id=workspace_id,
                source_id=source["source_id"],
                component="source_import_service",
                step="import",
                status="completed",
                refs={
                    "source_id": source["source_id"],
                    "source_input_mode": resolved.source_input_mode,
                },
            )
        except SourceImportError as exc:
            elapsed = max(time.perf_counter() - started_at, 0.0)
            _source_import_total.labels(
                source_input_mode=mode_hint,
                outcome="failed",
            ).inc()
            _source_import_duration_seconds.labels(
                source_input_mode=mode_hint,
                outcome="failed",
            ).observe(elapsed)
            logger.warning(
                "research.source_import.failed req=%s workspace=%s mode=%s elapsed_ms=%d code=%s message=%s",
                request_id,
                workspace_id,
                mode_hint,
                int(elapsed * 1000),
                exc.error_code,
                exc.message,
            )
            raise

        elapsed = max(time.perf_counter() - started_at, 0.0)
        mode_label = resolved.source_input_mode
        _source_import_total.labels(
            source_input_mode=mode_label,
            outcome="succeeded",
        ).inc()
        _source_import_duration_seconds.labels(
            source_input_mode=mode_label,
            outcome="succeeded",
        ).observe(elapsed)
        logger.info(
            "research.source_import.succeeded req=%s workspace=%s source_id=%s mode=%s elapsed_ms=%d content_chars=%d",
            request_id,
            workspace_id,
            source["source_id"],
            mode_label,
            int(elapsed * 1000),
            len(resolved.content),
        )
        return source

    def _resolve_source_payload(
        self,
        *,
        source_type: str,
        title: str | None,
        content: str | None,
        metadata: dict[str, object],
        source_input_mode: str,
        source_input: str | None,
        source_url: str | None,
        local_file: dict[str, object] | None,
    ) -> _ResolvedSourceImport:
        resolved_mode = self._detect_input_mode(
            source_input_mode=source_input_mode,
            source_input=source_input,
            source_url=source_url,
            local_file=local_file,
            content=content,
        )
        if resolved_mode == "url":
            return self._resolve_url_payload(
                source_type=source_type,
                title=title,
                source_input=source_input,
                source_url=source_url,
                content=content,
                metadata=metadata,
            )
        if resolved_mode == "local_file":
            return self._resolve_local_file_payload(
                source_type=source_type,
                title=title,
                content=content,
                local_file=local_file,
                metadata=metadata,
            )
        return self._resolve_manual_payload(
            source_type=source_type,
            title=title,
            content=content,
            source_input=source_input,
            metadata=metadata,
        )

    def _detect_input_mode(
        self,
        *,
        source_input_mode: str,
        source_input: str | None,
        source_url: str | None,
        local_file: dict[str, object] | None,
        content: str | None,
    ) -> str:
        normalized_mode = (source_input_mode or "auto").strip().lower()
        if normalized_mode not in {"auto", "manual_text", "url", "local_file"}:
            self._raise_invalid_request(
                "unsupported source_input_mode",
                {"source_input_mode": source_input_mode},
            )
        if normalized_mode != "auto":
            return normalized_mode
        if source_url and source_url.strip():
            return "url"
        if local_file is not None:
            return "local_file"
        auto_candidate = self._coalesce_text(source_input, content)
        if auto_candidate and self._looks_like_url(auto_candidate):
            return "url"
        return "manual_text"

    def _resolve_manual_payload(
        self,
        *,
        source_type: str,
        title: str | None,
        content: str | None,
        source_input: str | None,
        metadata: dict[str, object],
    ) -> _ResolvedSourceImport:
        manual_content = self._coalesce_text(source_input, content)
        if not manual_content:
            self._raise_invalid_request(
                "manual_text mode requires non-empty content",
                {"required_any_of": ["content", "source_input"]},
            )
        resolved_title = (title or "").strip() or self._derive_title(
            manual_content, source_type
        )
        return self._finalize_source_payload(
            source_input_mode="manual_text",
            source_type=source_type,
            title=resolved_title,
            content=manual_content,
            metadata=metadata,
            detected_url=None,
        )

    def _resolve_url_payload(
        self,
        *,
        source_type: str,
        title: str | None,
        source_input: str | None,
        source_url: str | None,
        content: str | None,
        metadata: dict[str, object],
    ) -> _ResolvedSourceImport:
        raw_url = self._coalesce_text(source_url, source_input, content)
        if not raw_url or not self._looks_like_url(raw_url):
            self._raise_invalid_request(
                "url mode requires a valid http/https URL",
                {"source_url": raw_url},
            )
        html = self._fetch_url_html(raw_url)
        canonical_url = self._extract_canonical_url(html) or raw_url
        extracted_text = self._extract_html_text(html)
        if not extracted_text:
            raise SourceImportError(
                error_code="research.source_import_parse_failed",
                message="failed to parse article text from URL",
                details={"source_url": raw_url},
                status_code=400,
            )
        extracted_title = self._extract_html_title(html)
        resolved_title = (title or "").strip() or extracted_title or canonical_url
        metadata_with_url = dict(metadata)
        metadata_with_url.setdefault("source_url", raw_url)
        metadata_with_url.setdefault("canonical_url", canonical_url)
        return self._finalize_source_payload(
            source_input_mode="url",
            source_type=source_type,
            title=resolved_title,
            content=extracted_text,
            metadata=metadata_with_url,
            detected_url=canonical_url,
        )

    def _resolve_local_file_payload(
        self,
        *,
        source_type: str,
        title: str | None,
        content: str | None,
        local_file: dict[str, object] | None,
        metadata: dict[str, object],
    ) -> _ResolvedSourceImport:
        if not isinstance(local_file, dict):
            self._raise_invalid_request(
                "local_file mode requires local_file payload",
                {"required": "local_file"},
            )
        file_name = str(local_file.get("file_name") or "").strip()
        local_path = str(local_file.get("local_path") or "").strip()
        if not file_name and not local_path:
            self._raise_invalid_request(
                "local_file payload requires file_name or local_path",
                {"required_any_of": ["local_file.file_name", "local_file.local_path"]},
            )
        suffix = Path(file_name).suffix.lower() if file_name else ""
        if not suffix and local_path:
            suffix = Path(local_path).suffix.lower()
        if suffix not in _SUPPORTED_LOCAL_FILE_EXTENSIONS:
            raise SourceImportError(
                error_code="research.source_import_unsupported_format",
                message="unsupported local file format",
                details={
                    "file_name": file_name,
                    "local_path": local_path,
                    "supported_extensions": sorted(_SUPPORTED_LOCAL_FILE_EXTENSIONS),
                },
                status_code=400,
            )
        file_bytes = self._load_local_file_bytes(local_file)
        parser_metadata: dict[str, object] | None = None
        if suffix == ".docx":
            extracted_text = self._extract_docx_text(file_bytes)
        else:
            pdf_document = self._extract_pdf_document(file_bytes)
            extracted_text = self._get_pdf_document_text(pdf_document)
            parser_metadata = self._get_pdf_document_metadata(pdf_document)
        supplemental_text = self._normalize_whitespace(content or "")
        if supplemental_text:
            extracted_text = f"{extracted_text}\n\n{supplemental_text}"
        normalized_text = self._normalize_whitespace(extracted_text)
        if not normalized_text:
            raise SourceImportError(
                error_code="research.source_import_parse_failed",
                message="local file text extraction produced empty content",
                details={"file_name": file_name, "local_path": local_path},
                status_code=400,
            )
        resolved_title = (
            (title or "").strip()
            or Path(file_name or local_path).stem
            or self._derive_title(normalized_text, source_type)
        )
        metadata_with_file = dict(metadata)
        metadata_with_file.setdefault(
            "local_file_name", file_name or Path(local_path).name
        )
        metadata_with_file.setdefault("local_file_format", suffix.lstrip("."))
        if parser_metadata is not None:
            metadata_with_file.setdefault("parser_metadata", parser_metadata)
        if local_path:
            metadata_with_file.setdefault("local_file_path", local_path)
        return self._finalize_source_payload(
            source_input_mode="local_file",
            source_type=source_type,
            title=resolved_title,
            content=normalized_text,
            metadata=metadata_with_file,
            detected_url=None,
        )

    def _fetch_url_html(self, source_url: str) -> str:
        request = urllib.request.Request(
            source_url,
            headers={"User-Agent": "EverMemOS-Research-Import/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status_code = getattr(response, "status", None) or response.getcode()
                if status_code and int(status_code) >= 400:
                    raise SourceImportError(
                        error_code="research.source_import_remote_fetch_failed",
                        message="failed to fetch URL content",
                        details={
                            "source_url": source_url,
                            "http_status": int(status_code),
                        },
                        status_code=502,
                    )
                charset = response.headers.get_content_charset() or "utf-8"
                raw = response.read()
        except SourceImportError:
            raise
        except urllib.error.URLError as exc:
            raise SourceImportError(
                error_code="research.source_import_remote_fetch_failed",
                message="failed to fetch URL content",
                details={"source_url": source_url, "reason": str(exc)},
                status_code=502,
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive fallback
            raise SourceImportError(
                error_code="research.source_import_remote_fetch_failed",
                message="failed to fetch URL content",
                details={"source_url": source_url, "reason": str(exc)},
                status_code=502,
            ) from exc
        return raw.decode(charset, errors="ignore")

    def _extract_html_title(self, html: str) -> str | None:
        match = _TITLE_RE.search(html)
        if not match:
            return None
        return self._normalize_whitespace(unescape(match.group(1))) or None

    def _extract_canonical_url(self, html: str) -> str | None:
        match = _CANONICAL_RE.search(html)
        if not match:
            return None
        return self._normalize_whitespace(unescape(match.group(1))) or None

    def _extract_html_text(self, html: str) -> str:
        without_scripts = re.sub(
            r"<script[^>]*>.*?</script>",
            " ",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        without_styles = re.sub(
            r"<style[^>]*>.*?</style>",
            " ",
            without_scripts,
            flags=re.IGNORECASE | re.DOTALL,
        )
        raw_text = re.sub(r"<[^>]+>", " ", without_styles)
        return self._normalize_whitespace(unescape(raw_text))

    def _load_local_file_bytes(self, local_file: dict[str, object]) -> bytes:
        encoded = str(local_file.get("file_content_base64") or "").strip()
        if encoded:
            try:
                return base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise SourceImportError(
                    error_code="research.source_import_parse_failed",
                    message="invalid local file base64 payload",
                    details={"reason": str(exc)},
                    status_code=400,
                ) from exc
        local_path = str(local_file.get("local_path") or "").strip()
        if not local_path:
            self._raise_invalid_request(
                "local_file payload requires file_content_base64 or local_path",
                {
                    "required_any_of": [
                        "local_file.file_content_base64",
                        "local_file.local_path",
                    ]
                },
            )
        try:
            return Path(local_path).expanduser().read_bytes()
        except Exception as exc:
            raise SourceImportError(
                error_code="research.source_import_parse_failed",
                message="failed to load local file",
                details={"local_path": local_path, "reason": str(exc)},
                status_code=400,
            ) from exc

    def _extract_docx_text(self, raw_bytes: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as docx_zip:
                xml_payload = docx_zip.read("word/document.xml")
            root = ElementTree.fromstring(xml_payload)
        except Exception as exc:
            raise SourceImportError(
                error_code="research.source_import_parse_failed",
                message="failed to parse docx file",
                details={"reason": str(exc)},
                status_code=400,
            ) from exc
        texts = [
            node.text.strip()
            for node in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
            if node.text and node.text.strip()
        ]
        return self._normalize_whitespace(" ".join(texts))

    def _extract_pdf_document(self, raw_bytes: bytes) -> StructuredPdfDocument:
        try:
            import fitz  # type: ignore[import-not-found]

            document = fitz.open(stream=raw_bytes, filetype="pdf")
            page_blocks: list[tuple[int, int, str]] = []
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                for block_index, block in enumerate(page.get_text("blocks") or []):
                    text = str(block[4] if len(block) > 4 else "")
                    page_blocks.append((page_index + 1, block_index, text))
            parsed = self._build_structured_pdf_document(
                parser="pymupdf",
                pages=int(document.page_count),
                page_blocks=page_blocks,
            )
            if parsed.text:
                return parsed
        except Exception:
            pass

        return self._extract_pdf_document_with_pypdf(raw_bytes)

    def _extract_pdf_document_with_pypdf(
        self, raw_bytes: bytes
    ) -> StructuredPdfDocument:
        pdf_reader_cls = None
        parser_name = "pypdf"
        try:
            from pypdf import PdfReader  # type: ignore[import-not-found]

            pdf_reader_cls = PdfReader
        except ImportError:
            try:
                from PyPDF2 import PdfReader  # type: ignore[import-not-found]

                pdf_reader_cls = PdfReader
                parser_name = "PyPDF2"
            except ImportError as exc:
                raise SourceImportError(
                    error_code="research.source_import_parse_failed",
                    message="pdf parser dependency is missing",
                    details={"missing_dependency": "pypdf_or_PyPDF2"},
                    status_code=400,
                ) from exc
        try:
            reader = pdf_reader_cls(io.BytesIO(raw_bytes))
            page_blocks = [
                (page_index + 1, 0, page.extract_text() or "")
                for page_index, page in enumerate(reader.pages)
            ]
            parsed = self._build_structured_pdf_document(
                parser=parser_name, pages=len(reader.pages), page_blocks=page_blocks
            )
            return parsed
        except Exception as exc:
            raise SourceImportError(
                error_code="research.source_import_parse_failed",
                message="failed to parse pdf file",
                details={"reason": str(exc)},
                status_code=400,
            ) from exc

    def _extract_pdf_text(self, raw_bytes: bytes) -> str:
        return self._get_pdf_document_text(self._extract_pdf_document(raw_bytes))

    def _build_structured_pdf_document(
        self, *, parser: str, pages: int, page_blocks: list[tuple[int, int, str]]
    ) -> StructuredPdfDocument:
        blocks: list[StructuredPdfBlock] = []
        text_parts: list[str] = []
        offset = 0
        for page_number, block_index, raw_text in page_blocks:
            text = self._normalize_whitespace(raw_text)
            if not text:
                continue
            if text_parts:
                offset += 1
            start = offset
            end = start + len(text)
            anchor_id = f"p{page_number}-b{block_index}"
            blocks.append(
                StructuredPdfBlock(
                    page_number=page_number,
                    block_index=block_index,
                    text=text,
                    anchor_id=anchor_id,
                    start=start,
                    end=end,
                    paragraph_ids=(f"{anchor_id}-par0",),
                )
            )
            text_parts.append(text)
            offset = end

        normalized_text = " ".join(text_parts)
        return StructuredPdfDocument(
            parser=parser,
            pages=pages,
            text=normalized_text,
            chars=len(normalized_text),
            blocks=tuple(blocks),
        )

    def _get_pdf_document_text(
        self, document: StructuredPdfDocument | dict[str, object]
    ) -> str:
        if isinstance(document, dict):
            return self._normalize_whitespace(str(document.get("text") or ""))
        return self._normalize_whitespace(document.text)

    def _get_pdf_document_metadata(
        self, document: StructuredPdfDocument | dict[str, object]
    ) -> dict[str, object]:
        if isinstance(document, dict):
            blocks = document.get("blocks")
            return {
                "parser": str(document.get("parser") or "unknown"),
                "pages": int(document.get("pages") or 0),
                "chars": int(
                    document.get("chars") or len(str(document.get("text") or ""))
                ),
                "blocks": blocks if isinstance(blocks, list) else [],
            }

        return {
            "parser": document.parser,
            "pages": document.pages,
            "chars": document.chars,
            "blocks": [
                {
                    "anchor_id": block.anchor_id,
                    "page_number": block.page_number,
                    "block_index": block.block_index,
                    "paragraph_ids": list(block.paragraph_ids),
                    "start": block.start,
                    "end": block.end,
                    "text": block.text,
                }
                for block in document.blocks
            ],
        }

    def _finalize_source_payload(
        self,
        *,
        source_input_mode: str,
        source_type: str,
        title: str,
        content: str,
        metadata: dict[str, object],
        detected_url: str | None,
    ) -> _ResolvedSourceImport:
        normalized_title = self._normalize_whitespace(title)
        normalized_content = self._sanitize_source_content(content)
        if not normalized_content:
            raise SourceImportError(
                error_code="research.source_import_parse_failed",
                message="resolved source content is empty",
                details={"source_input_mode": source_input_mode},
                status_code=400,
            )
        if not normalized_title:
            normalized_title = self._derive_title(normalized_content, "source")
        normalized_metadata = dict(metadata)
        if detected_url and "url" not in normalized_metadata:
            normalized_metadata["url"] = detected_url

        detected_doi = self._detect_doi(normalized_title)
        if not detected_doi and source_input_mode != "local_file":
            detected_doi = self._detect_doi(normalized_content)
        if not detected_doi and detected_url:
            detected_doi = self._detect_doi(detected_url)
        if detected_doi and "doi" not in normalized_metadata:
            normalized_metadata["doi"] = detected_doi

        if "publication_year" not in normalized_metadata:
            detected_year = self._detect_publication_year(normalized_content)
            if detected_year is not None:
                normalized_metadata["publication_year"] = detected_year
        normalized_metadata["topic_clusters"] = self._build_topic_clusters(
            title=normalized_title, content=normalized_content
        )
        normalized_metadata["topic_cluster_version"] = "deterministic_v2"
        if source_type == "paper":
            normalized_metadata["scholarly_enrichment_required"] = not (
                self._is_present_metadata_value(normalized_metadata.get("doi"))
                and self._is_present_metadata_value(normalized_metadata.get("authors"))
                and self._is_present_metadata_value(normalized_metadata.get("venue"))
            )

        normalized_metadata["source_input_mode"] = source_input_mode
        normalized_metadata["metadata_completeness_status"] = (
            self._compute_metadata_completeness_status(normalized_metadata)
        )
        return _ResolvedSourceImport(
            source_input_mode=source_input_mode,
            title=normalized_title,
            content=normalized_content,
            metadata=normalized_metadata,
        )

    def _derive_title(self, content: str, source_type: str) -> str:
        normalized = self._normalize_whitespace(content)
        if not normalized:
            return f"{source_type}_source"
        return normalized[:96]

    def _compute_metadata_completeness_status(self, metadata: dict[str, object]) -> str:
        fields = [
            metadata.get("doi"),
            metadata.get("url"),
            metadata.get("publication_year"),
            metadata.get("authors"),
            metadata.get("venue"),
        ]
        count = sum(1 for value in fields if self._is_present_metadata_value(value))
        if (
            self._is_present_metadata_value(metadata.get("publication_year"))
            and self._is_present_metadata_value(metadata.get("topic_clusters"))
            and count < 2
        ):
            return "partial"
        if count >= 4:
            return "high"
        if count >= 2:
            return "partial"
        return "minimal"

    def _is_present_metadata_value(self, value: object | None) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True

    def _coalesce_text(self, *values: str | None) -> str:
        for value in values:
            if value is None:
                continue
            normalized = self._normalize_whitespace(value)
            if normalized:
                return normalized
        return ""

    def _estimate_payload_bytes(
        self,
        *,
        source_input_mode: str,
        source_input: str | None,
        source_url: str | None,
        content: str | None,
        local_file: dict[str, object] | None,
    ) -> int:
        if source_input_mode == "local_file" and isinstance(local_file, dict):
            encoded = str(local_file.get("file_content_base64") or "").strip()
            if encoded:
                return max((len(encoded) * 3) // 4, 0)
            local_path = str(local_file.get("local_path") or "").strip()
            if local_path:
                try:
                    return int(Path(local_path).expanduser().stat().st_size)
                except Exception:
                    return len(local_path.encode("utf-8"))
        total = 0
        for value in (source_input, source_url, content):
            if value is None:
                continue
            total += len(str(value).encode("utf-8"))
        return max(total, 0)

    def _normalize_whitespace(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value or "")
        return re.sub(r"\s+", " ", normalized).strip()

    def _sanitize_source_content(self, value: str) -> str:
        sanitized = unicodedata.normalize("NFKC", value or "")
        sanitized = _FILE_URL_RE.sub(" ", sanitized)
        sanitized = _LOCAL_FILE_PATH_RE.sub(" ", sanitized)
        sanitized = _FILE_NAME_NOISE_RE.sub(" ", sanitized)
        sanitized = _PAGE_FOOTER_RE.sub(" ", sanitized)
        sanitized = _PAGE_INDEX_RE.sub(" ", sanitized)
        sanitized = _DATETIME_FOOTER_RE.sub(" ", sanitized)
        return self._normalize_whitespace(sanitized)

    def _looks_like_url(self, value: str) -> bool:
        return bool(_URL_RE.fullmatch(value.strip()))

    def _detect_doi(self, value: str) -> str | None:
        match = _DOI_RE.search(value)
        if not match:
            return None
        return match.group(0)

    def _detect_publication_year(self, value: str) -> int | None:
        upper_bound = time.gmtime().tm_year + 1
        candidates = [
            int(match)
            for match in _YEAR_RE.findall(value)
            if 1900 <= int(match) <= upper_bound
        ]
        if not candidates:
            return None
        year_counter = CollectionsCounter(candidates)
        ranked = sorted(year_counter.items(), key=lambda item: (-item[1], -item[0]))
        return int(ranked[0][0])

    def _build_topic_clusters(
        self, *, title: str, content: str
    ) -> list[dict[str, object]]:
        weighted_text = f"{title}\n{title}\n{content}"
        all_terms = self._extract_topic_terms(weighted_text)
        if not all_terms:
            return []

        term_counts = CollectionsCounter(all_terms)
        ranked_terms = [
            term
            for term, _ in sorted(
                term_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ]
        seed_terms: list[str] = []
        for priority in _TOPIC_PRIORITY_TERMS:
            if priority in term_counts and priority not in seed_terms:
                seed_terms.append(priority)
        for term in ranked_terms:
            if term in seed_terms:
                continue
            seed_terms.append(term)
            if len(seed_terms) >= 6:
                break
        sentence_terms = [
            set(self._extract_topic_terms(chunk))
            for chunk in _TOPIC_SENTENCE_SPLIT_RE.split(weighted_text)
            if chunk.strip()
        ]
        co_occurrence: dict[str, CollectionsCounter[str]] = defaultdict(
            CollectionsCounter
        )
        seed_hits: CollectionsCounter[str] = CollectionsCounter()
        for sentence in sentence_terms:
            if not sentence:
                continue
            for seed in seed_terms:
                if seed not in sentence:
                    continue
                seed_hits[seed] += 1
                for term in sentence:
                    if term == seed:
                        continue
                    co_occurrence[seed][term] += 1

        clusters: list[dict[str, object]] = []
        seen_keyword_signatures: set[tuple[str, ...]] = set()
        for seed in seed_terms:
            neighbors = [
                term
                for term, _ in sorted(
                    co_occurrence[seed].items(), key=lambda item: (-item[1], item[0])
                )
                if term_counts.get(term, 0) > 1
            ][:4]
            keywords = [seed, *neighbors]
            signature = tuple(keywords)
            if signature in seen_keyword_signatures:
                continue
            is_priority_seed = seed in _TOPIC_PRIORITY_TERMS
            if len(signature) < 2 and not is_priority_seed:
                continue
            seen_keyword_signatures.add(signature)
            clusters.append(
                {
                    "cluster_id": f"topic_{seed}",
                    "cluster_label": seed.replace("_", " "),
                    "keywords": keywords,
                    "signal_score": int(term_counts.get(seed, 0) + len(neighbors)),
                    "evidence_hits": int(seed_hits.get(seed, 0)),
                }
            )
            if len(clusters) >= 4:
                break
        return clusters

    def _extract_topic_terms(self, text: str) -> list[str]:
        normalized = text.lower()
        priority_terms = [term for term in _TOPIC_PRIORITY_TERMS if term in text]
        latin_terms = [
            token
            for token in _TOPIC_LATIN_TOKEN_RE.findall(normalized)
            if token not in _TOPIC_STOPWORDS and not self._is_topic_noise_token(token)
        ]
        cjk_terms = [
            token
            for token in _TOPIC_CJK_TOKEN_RE.findall(text)
            if token not in _TOPIC_STOPWORDS
            and token not in _TOPIC_CJK_STOPWORDS
            and not self._is_topic_noise_token(token.lower())
        ]
        return [*priority_terms, *latin_terms, *cjk_terms]

    def _is_topic_noise_token(self, token: str) -> bool:
        if token in _TOPIC_NOISE_TOKENS:
            return True
        return bool(_TOPIC_PATH_NOISE_TOKEN_RE.fullmatch(token))

    def _raise_invalid_request(
        self, message: str, details: dict[str, object] | None = None
    ) -> None:
        raise SourceImportError(
            error_code="research.invalid_request",
            message=message,
            details=details,
            status_code=400,
        )
