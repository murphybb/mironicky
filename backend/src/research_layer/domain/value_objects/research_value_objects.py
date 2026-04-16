from __future__ import annotations

import re
from dataclasses import dataclass


_WORKSPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-:.]{2,63}$")


@dataclass(frozen=True, slots=True)
class WorkspaceId:
    value: str

    def __post_init__(self) -> None:
        raw = self.value.strip()
        if not _WORKSPACE_PATTERN.match(raw):
            raise ValueError("workspace_id must match ^[A-Za-z0-9][A-Za-z0-9_\\-:.]{2,63}$")
        object.__setattr__(self, "value", raw)

    @classmethod
    def parse(cls, raw: str) -> "WorkspaceId":
        return cls(value=raw)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class TopFactor:
    name: str
    score: float

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("top factor name cannot be empty")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("top factor score must be in [0, 1]")
        object.__setattr__(self, "name", self.name.strip())

    def to_dict(self) -> dict[str, float | str]:
        return {"name": self.name, "score": self.score}

    @classmethod
    def from_dict(cls, payload: dict[str, float | str]) -> "TopFactor":
        return cls(name=str(payload["name"]), score=float(payload["score"]))


@dataclass(frozen=True, slots=True)
class ScoreMeta:
    support: float
    risk: float
    progressability: float

    def __post_init__(self) -> None:
        for field_name, value in (
            ("support", self.support),
            ("risk", self.risk),
            ("progressability", self.progressability),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be in [0, 1]")

    def to_dict(self) -> dict[str, float]:
        return {
            "support": self.support,
            "risk": self.risk,
            "progressability": self.progressability,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, float]) -> "ScoreMeta":
        return cls(
            support=float(payload["support"]),
            risk=float(payload["risk"]),
            progressability=float(payload["progressability"]),
        )
