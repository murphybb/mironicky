from __future__ import annotations

import re
from pathlib import Path

from research_layer.extractors.types import (
    ExtractedCandidate,
    ExtractFailureError,
    SourceSpan,
)
from research_layer.services.source_parser import ParsedSource


class KeywordExtractor:
    candidate_type: str
    extractor_name: str
    keywords: tuple[str, ...]
    prompt_file_name: str

    def build_fallback_candidates(
        self, parsed: ParsedSource
    ) -> list[ExtractedCandidate]:
        marker = f"[[EXTRACT_FAIL:{self.extractor_name}]]"
        if marker in parsed.normalized_content:
            raise ExtractFailureError(
                self.extractor_name, "extractor marker requested failure"
            )

        candidates: list[ExtractedCandidate] = []
        for segment in parsed.segments:
            if not self._segment_matches_keywords(segment.text):
                continue
            candidates.append(
                ExtractedCandidate(
                    candidate_type=self.candidate_type,
                    text=segment.text,
                    source_span=SourceSpan(
                        start=segment.start, end=segment.end, text=segment.text
                    ),
                    extractor_name=self.extractor_name,
                )
            )
        return candidates

    def _segment_matches_keywords(self, text: str) -> bool:
        normalized = text.lower()
        return any(
            re.search(
                rf"(?<![a-z0-9_]){re.escape(keyword.lower())}(?![a-z0-9_])", normalized
            )
            for keyword in self.keywords
        )

    # Backward-compatible alias used by older tests/helpers.
    def extract(self, parsed: ParsedSource) -> list[ExtractedCandidate]:
        return self.build_fallback_candidates(parsed)

    @property
    def prompt_path(self) -> Path:
        return Path(__file__).resolve().parents[1] / "prompts" / self.prompt_file_name
