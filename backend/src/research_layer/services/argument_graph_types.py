from __future__ import annotations

UNIT_TYPE_MAP = {
    "claim": "conclusion",
    "hypothesis": "assumption",
    "premise": "assumption",
    "condition": "assumption",
    "evidence": "evidence",
    "method": "evidence",
    "result": "evidence",
    "finding": "evidence",
    "concept": "evidence",
    "entity": "evidence",
    "definition": "evidence",
    "citation": "evidence",
    "measurement": "evidence",
    "metric": "evidence",
    "sample": "evidence",
    "dataset": "evidence",
    "equation": "evidence",
    "figure": "evidence",
    "code": "evidence",
    "theorem": "conclusion",
    "proof_step": "evidence",
    "population": "evidence",
    "intervention": "evidence",
    "outcome": "evidence",
    "statistical_test": "evidence",
    "assumption": "assumption",
    "limitation": "gap",
    "question": "gap",
    "contradiction": "conflict",
    "conflict": "conflict",
    "open_question": "gap",
    "gap": "gap",
}

RELATION_TYPE_MAP = {
    "supports": "supports",
    "defines": "supports",
    "cites": "supports",
    "measures": "supports",
    "compares_with": "supports",
    "correlates_with": "supports",
    "improves_over": "supports",
    "same_as": "supports",
    "extends": "supports",
    "relies_on": "requires",
    "requires": "requires",
    "uses": "requires",
    "part_of": "requires",
    "contradicts": "conflicts",
    "limits": "weakens",
    "weakens": "weakens",
    "leads_to": "derives",
    "causes": "derives",
    "derived_from": "derives",
    "derives": "derives",
    "validates": "validates",
}


def normalize_unit_type(raw_type: str) -> str:
    return UNIT_TYPE_MAP[str(raw_type).strip().lower()]


def normalize_relation_type(raw_type: str) -> str:
    return RELATION_TYPE_MAP[str(raw_type).strip().lower()]
