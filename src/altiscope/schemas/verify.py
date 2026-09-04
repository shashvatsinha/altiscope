"""Verification verdict for one claim, produced by a model other than the producer."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

VERIFY_SCHEMA_VERSION = 1


class Verdict(StrEnum):
    supported = "supported"
    partially_supported = "partially_supported"
    unsupported = "unsupported"
    cannot_determine = "cannot_determine"


class VerificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    rationale: str = Field(min_length=1, description="Names the evidence that decided it.")
