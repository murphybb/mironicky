from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSegment:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class ParsedSource:
    source_type: str
    normalized_content: str
    segments: list[ParsedSegment]


class ParseFailureError(RuntimeError):
    pass


class SourceParser:
    _split_pattern = re.compile(r"[^\n.!?\u3002\uff01\uff1f\uff1b;]+(?:[.!?\u3002\uff01\uff1f\uff1b;]+|$)")

    def parse(self, *, source_type: str, content: str) -> ParsedSource:
        normalized = self._normalize_content(content)
        if "[[PARSE_FAIL]]" in normalized:
            raise ParseFailureError("parser marker requested failure")
        if not normalized:
            raise ParseFailureError("empty normalized content")

        segments = self._extract_segments(normalized)
        if not segments:
            raise ParseFailureError("no parseable segments found")

        return ParsedSource(
            source_type=source_type,
            normalized_content=normalized,
            segments=segments,
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

