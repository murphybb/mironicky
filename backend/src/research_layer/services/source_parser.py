from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSegment:
    start: int
    end: int
    text: str
    artifact_type: str = "text"
    raw_text: str | None = None
    page: int | None = None
    block_id: str | None = None
    paragraph_id: str | None = None
    section_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedSource:
    source_type: str
    normalized_content: str
    segments: list[ParsedSegment]


class ParseFailureError(RuntimeError):
    pass


class SourceParser:
    _split_pattern = re.compile(
        r"[^\n.!?\u3002\uff01\uff1f\uff1b;]+(?:[.!?\u3002\uff01\uff1f\uff1b;]+|$)"
    )

    def parse(
        self,
        *,
        source_type: str,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> ParsedSource:
        normalized = self._normalize_content(content)
        if "[[PARSE_FAIL]]" in normalized:
            raise ParseFailureError("parser marker requested failure")
        if not normalized:
            raise ParseFailureError("empty normalized content")

        segments = self._extract_structured_segments(
            metadata
        ) or self._extract_segments(normalized)
        if not segments:
            raise ParseFailureError("no parseable segments found")

        return ParsedSource(
            source_type=source_type, normalized_content=normalized, segments=segments
        )

    def _normalize_content(self, content: str) -> str:
        return re.sub(r"\s+", " ", content).strip()

    def _extract_segments(self, normalized_content: str) -> list[ParsedSegment]:
        segments: list[ParsedSegment] = []
        for match in self._split_pattern.finditer(normalized_content):
            text = match.group(0).strip()
            if not text:
                continue
            raw_start = match.start()
            leading = len(match.group(0)) - len(match.group(0).lstrip())
            start = raw_start + leading
            end = start + len(text)
            segments.append(ParsedSegment(start=start, end=end, text=text))
        return segments

    def _extract_structured_segments(
        self, metadata: dict[str, object] | None
    ) -> list[ParsedSegment]:
        if not isinstance(metadata, dict):
            return []
        parser_metadata = metadata.get("parser_metadata")
        if not isinstance(parser_metadata, dict):
            return []
        blocks = parser_metadata.get("blocks")
        if not isinstance(blocks, list):
            return []

        segments: list[ParsedSegment] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            raw_block_text = str(block.get("raw_text") or block.get("text") or "")
            block_text = self._normalize_content(str(block.get("text") or raw_block_text))
            if not block_text:
                continue
            block_start = self._coerce_int(block.get("start"), default=0)
            page = self._coerce_optional_int(
                block.get("page_number") or block.get("page")
            )
            block_id = (
                str(block.get("anchor_id") or block.get("block_id") or "").strip()
                or None
            )
            paragraph_ids = block.get("paragraph_ids")
            paragraph_id = None
            if isinstance(paragraph_ids, list) and paragraph_ids:
                paragraph_id = str(paragraph_ids[0])
            section_path = block.get("section_path")
            normalized_section_path = (
                tuple(str(item) for item in section_path)
                if isinstance(section_path, list)
                else ()
            )

            if self._looks_like_table_block(raw_block_text or block_text):
                segments.append(
                    ParsedSegment(
                        start=block_start,
                        end=block_start + len(block_text),
                        text=block_text,
                        artifact_type="table",
                        raw_text=raw_block_text.strip() or block_text,
                        page=page,
                        block_id=block_id,
                        paragraph_id=paragraph_id,
                        section_path=normalized_section_path,
                    )
                )
                continue
            block_artifact_type = self._classify_block_artifact(raw_block_text or block_text)
            if block_artifact_type in {"formula", "figure", "code"}:
                segments.append(
                    ParsedSegment(
                        start=block_start,
                        end=block_start + len(block_text),
                        text=block_text,
                        artifact_type=block_artifact_type,
                        raw_text=raw_block_text.strip() or block_text,
                        page=page,
                        block_id=block_id,
                        paragraph_id=paragraph_id,
                        section_path=normalized_section_path,
                    )
                )
                continue

            for segment in self._extract_segments(block_text):
                segments.append(
                    ParsedSegment(
                        start=block_start + segment.start,
                        end=block_start + segment.end,
                        text=segment.text,
                        artifact_type=block_artifact_type,
                        raw_text=segment.text,
                        page=page,
                        block_id=block_id,
                        paragraph_id=paragraph_id,
                        section_path=normalized_section_path,
                    )
                )
        return segments

    def _looks_like_table_block(self, text: str) -> bool:
        if "\t" in text or "|" in text:
            return True
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) >= 3:
            numeric_lines = sum(1 for line in lines if len(re.findall(r"\d", line)) >= 2)
            return numeric_lines >= 2
        tokens = text.split()
        numeric_tokens = sum(1 for token in tokens if re.search(r"\d", token))
        return len(tokens) >= 6 and numeric_tokens >= 4

    def _classify_block_artifact(self, text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return "text"
        if re.search(
            r"^(图|Figure|Fig\.?)\s*[\d一二三四五六七八九十]",
            stripped,
            re.I,
        ):
            return "figure"
        if re.search(
            r"^[（(]?\d+[）)]?\s*[=≈∑∫√]|[=≈]\s*[-+]?\d|[=≈].*(∑|∫|√|∇|Δ|α|β|γ|η|λ|μ|σ|θ|π|x_[{(]|[A-Za-z]\()",
            stripped,
        ):
            return "formula"
        if self._looks_like_code_block(stripped):
            return "code"
        return "text"

    def _looks_like_code_block(self, text: str) -> bool:
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            return False
        code_markers = sum(
            1
            for line in lines
            if re.search(
                r"(def |class |return |if |else:|for |while |\{|\}|=>|#include|public |private |const |let |var |import )",
                line,
            )
        )
        indented_lines = sum(
            1 for line in lines if line.startswith(("    ", "\t")) or re.match(r"^\d+\.\s", line)
        )
        return code_markers >= 2 or (code_markers >= 1 and indented_lines >= 1)

    def _coerce_int(self, value: object, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _coerce_optional_int(self, value: object) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
