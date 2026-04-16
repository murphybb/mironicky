from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    pass


class ResearchSourceType(StrEnum):
    PAPER = "paper"
    NOTE = "note"
    FEEDBACK = "feedback"
    FAILURE_RECORD = "failure_record"
    DIALOGUE = "dialogue"


class ResearchSourceStatus(StrEnum):
    RAW = "raw"
    PARSED = "parsed"
    INDEXED = "indexed"
    EXTRACTED = "extracted"


class EvidenceType(StrEnum):
    CLAIM = "claim"
    METHOD = "method"
    RESULT = "result"
    LIMITATION = "limitation"
    OBSERVATION = "observation"


class PriorWorkRelation(StrEnum):
    DIRECT_SUPPORT = "direct_support"
    RECOMBINATION = "recombination"
    UPSTREAM_INSPIRATION = "upstream_inspiration"


class AssumptionType(StrEnum):
    EXPLICIT = "explicit"
    IMPLICIT = "implicit"
    GENERATED = "generated"


class AssumptionStatus(StrEnum):
    ACTIVE = "active"
    CHALLENGED = "challenged"
    INVALIDATED = "invalidated"
    ARCHIVED = "archived"


class ConflictSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FailureSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ValidationLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class NoveltyLevel(StrEnum):
    CONSERVATIVE = "conservative"
    INCREMENTAL = "incremental"
    NOVEL = "novel"
    BREAKTHROUGH = "breakthrough"


class RouteStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    WEAKENED = "weakened"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    VALIDATED = "validated"


class GraphNodeType(StrEnum):
    CONCLUSION = "conclusion"
    EVIDENCE = "evidence"
    ASSUMPTION = "assumption"
    CONFLICT = "conflict"
    FAILURE = "failure"
    VALIDATION = "validation"
    BRANCH = "branch"
    GAP = "gap"
    PRIVATE_DEPENDENCY = "private_dependency"


class VisibilityLevel(StrEnum):
    PRIVATE = "private"
    WORKSPACE = "workspace"
    PACKAGE_PUBLIC = "package_public"


class GraphNodeStatus(StrEnum):
    ACTIVE = "active"
    WEAKENED = "weakened"
    CONFLICTED = "conflicted"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class GraphEdgeType(StrEnum):
    SUPPORTS = "supports"
    REQUIRES = "requires"
    CONFLICTS = "conflicts"
    WEAKENS = "weakens"
    DERIVES = "derives"
    VALIDATES = "validates"
    BRANCHES_TO = "branches_to"


class GraphEdgeStatus(StrEnum):
    ACTIVE = "active"
    WEAKENED = "weakened"
    CONFLICTED = "conflicted"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class GraphTriggerType(StrEnum):
    NEW_SOURCE = "new_source"
    CONFIRM_CANDIDATE = "confirm_candidate"
    MANUAL_EDIT = "manual_edit"
    FAILURE = "failure"
    VALIDATION_RESULT = "validation_result"
    RECOMPUTE = "recompute"
