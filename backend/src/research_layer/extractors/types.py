from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpan:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class ExtractedCandidate:
    candidate_type: str
    text: str
    source_span: SourceSpan
    extractor_name: str


class ExtractFailureError(RuntimeError):
    def __init__(self, extractor: str, message: str) -> None:
        super().__init__(message)
        self.extractor = extractor
