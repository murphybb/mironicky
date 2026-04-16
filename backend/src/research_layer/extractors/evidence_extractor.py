from __future__ import annotations

from research_layer.extractors._base import KeywordExtractor


class EvidenceExtractor(KeywordExtractor):
    candidate_type = "evidence"
    extractor_name = "evidence"
    prompt_file_name = "evidence_extractor_prompt.txt"
    keywords = (
        "claim",
        "method",
        "result",
        "observation",
        "limitation",
        "expected difference",
        "cause",
    )
