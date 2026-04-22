from __future__ import annotations

UNIT_TYPE_MAP = {
    "claim": "conclusion",
    "evidence": "evidence",
    "premise": "assumption",
    "contradiction": "conflict",
    "open_question": "gap",
}

RELATION_TYPE_MAP = {
    "supports": "supports",
    "relies_on": "requires",
    "contradicts": "conflicts",
    "leads_to": "derives",
}


def normalize_unit_type(raw_type: str) -> str:
    return UNIT_TYPE_MAP[str(raw_type).strip().lower()]


def normalize_relation_type(raw_type: str) -> str:
    return RELATION_TYPE_MAP[str(raw_type).strip().lower()]
