from __future__ import annotations

from research_layer.extractors._base import KeywordExtractor


class AssumptionExtractor(KeywordExtractor):
    candidate_type = "assumption"
    extractor_name = "assumption"
    prompt_file_name = "assumption_extractor_prompt.txt"
    keywords = (
        "assumption",
        "assume",
        "hypothesis",
        "limitation",
    )
