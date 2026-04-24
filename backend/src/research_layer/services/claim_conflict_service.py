from __future__ import annotations

import re

from research_layer.api.controllers._state_store import ResearchApiStateStore

NEGATION_PATTERNS = (
    re.compile(r"\bdoes\s+not\b", re.IGNORECASE),
    re.compile(r"\bdo\s+not\b", re.IGNORECASE),
    re.compile(r"\bdid\s+not\b", re.IGNORECASE),
    re.compile(r"\bcannot\b", re.IGNORECASE),
    re.compile(r"\bcan\s+not\b", re.IGNORECASE),
    re.compile(r"\bfails\s+to\b", re.IGNORECASE),
    re.compile(r"\bfail\s+to\b", re.IGNORECASE),
    re.compile(r"\bnot\b", re.IGNORECASE),
    re.compile(r"\bno\b", re.IGNORECASE),
)
CHINESE_NEGATION_MARKERS = ("没有", "不能", "无法", "未", "不")
NON_NEGATING_NOT_PATTERNS = (
    re.compile(r"\bnot\s+only\b", re.IGNORECASE),
    re.compile(r"\bnot\s+merely\b", re.IGNORECASE),
    re.compile(r"\bnot\s+just\b", re.IGNORECASE),
)
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "but",
    "by",
    "did",
    "do",
    "does",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "merely",
    "of",
    "on",
    "only",
    "or",
    "percent",
    "percentage",
    "than",
    "that",
    "the",
    "these",
    "this",
    "those",
    "to",
    "was",
    "were",
    "with",
}
CANONICAL_TOKENS = {
    "contradicted": "contradict",
    "contradicting": "contradict",
    "contradicts": "contradict",
    "decreased": "decrease",
    "decreases": "decrease",
    "decreasing": "decrease",
    "improved": "improve",
    "improves": "improve",
    "improving": "improve",
    "increased": "increase",
    "increases": "increase",
    "increasing": "increase",
    "supported": "support",
    "supporting": "support",
    "supports": "support",
    "worsened": "worsen",
    "worsening": "worsen",
    "worsens": "worsen",
}
ANTONYM_PAIRS = {
    ("contradict", "support"),
    ("decrease", "increase"),
    ("improve", "worsen"),
}
ANTONYM_LOOKUP = {
    left: right
    for pair in ANTONYM_PAIRS
    for left, right in (pair, (pair[1], pair[0]))
}


class ClaimConflictService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def detect_for_claim(
        self,
        *,
        workspace_id: str,
        new_claim_id: str,
        candidate_claim_ids: list[str],
        request_id: str,
    ) -> dict[str, object]:
        new_claim = self._store.get_claim(new_claim_id)
        if new_claim is None or str(new_claim["workspace_id"]) != workspace_id:
            return {"created_count": 0, "conflict_ids": []}

        created_ids: list[str] = []
        for existing_id in candidate_claim_ids:
            existing = self._store.get_claim(str(existing_id))
            if existing is None or existing["claim_id"] == new_claim["claim_id"]:
                continue
            if str(existing["workspace_id"]) != workspace_id:
                continue
            if not self._looks_contradictory(
                str(new_claim["normalized_text"]),
                str(existing["normalized_text"]),
            ):
                continue
            conflict = self._store.create_claim_conflict(
                workspace_id=workspace_id,
                new_claim_id=str(new_claim["claim_id"]),
                existing_claim_id=str(existing["claim_id"]),
                conflict_type="possible_contradiction",
                status="needs_review",
                evidence={
                    "new_text": new_claim["text"],
                    "existing_text": existing["text"],
                    "detector": "negation_overlap_v1",
                },
                source_ref={
                    "new_claim_id": new_claim["claim_id"],
                    "existing_claim_id": existing["claim_id"],
                    "new_source_id": new_claim["source_id"],
                    "existing_source_id": existing["source_id"],
                    "new_source_span": new_claim.get("source_span", {}),
                    "existing_source_span": existing.get("source_span", {}),
                },
                created_request_id=request_id,
            )
            created_ids.append(str(conflict["conflict_id"]))
        return {"created_count": len(created_ids), "conflict_ids": created_ids}

    def _looks_contradictory(self, new_text: str, existing_text: str) -> bool:
        new_negated, new_tokens = self._polarity_tokens(new_text)
        existing_negated, existing_tokens = self._polarity_tokens(existing_text)
        if not new_tokens or not existing_tokens:
            return False
        if self._has_antonym_pair(new_tokens, existing_tokens):
            return self._overlap_without_antonyms(new_tokens, existing_tokens) >= 0.5
        if new_negated == existing_negated:
            return False
        overlap = len(new_tokens & existing_tokens) / max(
            1, min(len(new_tokens), len(existing_tokens))
        )
        return overlap >= 0.6

    def _polarity_tokens(self, text: str) -> tuple[bool, set[str]]:
        normalized = text.lower()
        for pattern in NON_NEGATING_NOT_PATTERNS:
            normalized = pattern.sub(" ", normalized)
        negated = any(pattern.search(normalized) for pattern in NEGATION_PATTERNS)
        for marker in CHINESE_NEGATION_MARKERS:
            if marker in normalized:
                negated = True
                normalized = normalized.replace(marker, " ")
        for pattern in NEGATION_PATTERNS:
            normalized = pattern.sub(" ", normalized)
        tokens = {
            self._stem_token(token)
            for token in re.findall(r"[\w\u4e00-\u9fff]+", normalized)
            if len(token) > 1 and not token.isdigit()
        }
        return negated, {token for token in tokens if token and token not in STOPWORDS}

    def _stem_token(self, token: str) -> str:
        if re.search(r"[\u4e00-\u9fff]", token):
            return token
        if token in CANONICAL_TOKENS:
            return CANONICAL_TOKENS[token]
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            return token[:-1]
        return token

    def _has_antonym_pair(self, new_tokens: set[str], existing_tokens: set[str]) -> bool:
        return any(ANTONYM_LOOKUP.get(token) in existing_tokens for token in new_tokens)

    def _overlap_without_antonyms(
        self, new_tokens: set[str], existing_tokens: set[str]
    ) -> float:
        polarity_tokens = set(ANTONYM_LOOKUP) | set(ANTONYM_LOOKUP.values())
        new_context = new_tokens - polarity_tokens
        existing_context = existing_tokens - polarity_tokens
        return len(new_context & existing_context) / max(
            1, min(len(new_context), len(existing_context))
        )
