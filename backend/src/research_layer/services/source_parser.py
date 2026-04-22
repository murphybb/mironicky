from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSegment:
    start: int
    end: int
    text: str
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
            block_text = self._normalize_content(str(block.get("text") or ""))
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

            for segment in self._extract_segments(block_text):
                segments.append(
                    ParsedSegment(
                        start=block_start + segment.start,
                        end=block_start + segment.end,
                        text=segment.text,
                        page=page,
                        block_id=block_id,
                        paragraph_id=paragraph_id,
                        section_path=normalized_section_path,
                    )
                )
        return segments

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
