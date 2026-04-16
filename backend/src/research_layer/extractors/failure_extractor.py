from __future__ import annotations

from research_layer.extractors._base import KeywordExtractor


class FailureExtractor(KeywordExtractor):
    candidate_type = "failure"
    extractor_name = "failure"
    prompt_file_name = "failure_extractor_prompt.txt"
    keywords = (
        "failure",
        "failed",
        "error",
        "timed out",
        "cause",
    )
