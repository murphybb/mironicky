from __future__ import annotations

from research_layer.extractors._base import KeywordExtractor


class ConflictExtractor(KeywordExtractor):
    candidate_type = "conflict"
    extractor_name = "conflict"
    prompt_file_name = "conflict_extractor_prompt.txt"
    keywords = (
        "conflict",
        "contradict",
        "inconsistent",
        "mismatch",
    )
