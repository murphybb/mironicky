from __future__ import annotations

from research_layer.extractors._base import KeywordExtractor


class ValidationExtractor(KeywordExtractor):
    candidate_type = "validation"
    extractor_name = "validation"
    prompt_file_name = "validation_extractor_prompt.txt"
    keywords = (
        "validation",
        "experiment",
        "test",
        "ablation",
        "evaluate",
    )
