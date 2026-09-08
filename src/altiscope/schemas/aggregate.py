"""Aggregate summary: what the model emits when composing many sources into one view."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

AGGREGATE_SCHEMA_VERSION = 2


class Altitude(StrEnum):
    ic = "ic"
    manager = "manager"
    exec = "exec"

    @classmethod
    def from_str(cls, val: str) -> Altitude:
        normalized = val.strip().lower()
        if normalized in ("ic", "engineer", "dev", "tech"):
            return cls.ic
        if normalized in ("manager", "lead", "em"):
            return cls.manager
        if normalized in ("exec", "executive", "leadership", "director"):
            return cls.exec
        return cls(normalized)


class AggregateClaimKind(StrEnum):
    feature = "feature"
    bugfix = "bugfix"
    refactor = "refactor"
    infra = "infra"
    test = "test"
    docs = "docs"
    perf = "perf"
    security = "security"
    dependency = "dependency"
    chore = "chore"
    other = "other"
    theme = "theme"


class AggregateClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AggregateClaimKind
    text: str = Field(min_length=1)
    sources: list[str] = Field(
        min_length=1,
        description="Opaque source PR tokens (e.g. PR-42) exactly as shown in the material.",
    )


class AggregateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1)
    claims: list[AggregateClaim] = Field(min_length=1)
    narrative: str = Field(min_length=1)
