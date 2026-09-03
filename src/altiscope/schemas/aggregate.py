"""Aggregate summary: what the model emits when composing many sources into one view."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

AGGREGATE_SCHEMA_VERSION = 1


class Altitude(StrEnum):
    ic = "ic"
    lead = "lead"
    manager = "manager"
    director = "director"
    exec = "exec"


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
        description="Opaque source claim tokens exactly as shown in the material.",
    )


class AggregateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1)
    claims: list[AggregateClaim] = Field(min_length=1)
    narrative: str = Field(min_length=1)
