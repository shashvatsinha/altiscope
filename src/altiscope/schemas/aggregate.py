"""Aggregate summary: what the model emits when composing many sources into one view."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

AGGREGATE_SCHEMA_VERSION = 4


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


class AggregateSection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    heading: str = Field(min_length=1)
    text: str = Field(min_length=1)


class AggregateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    headline: str = Field(min_length=1)
    sections: list[AggregateSection] = Field(min_length=1)
    narrative: str = Field(min_length=1)
