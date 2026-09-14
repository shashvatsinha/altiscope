"""Versioned output contracts for independent assessment.

Schema 1 is retained only as historical context for old prompt rows. It is not
registered as an executable recipe contract. Schema 2 assesses one complete saved
result against the complete saved material that produced it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

VERIFY_SCHEMA_VERSION = 1
ASSESSMENT_SCHEMA_VERSION = 2


class Verdict(StrEnum):
    supported = "supported"
    partially_supported = "partially_supported"
    unsupported = "unsupported"
    cannot_determine = "cannot_determine"


class VerificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    rationale: str = Field(min_length=1, description="Names the evidence that decided it.")


class AssessmentVerdict(StrEnum):
    agree = "agree"
    disagree = "disagree"
    inconclusive = "inconclusive"


class AssessmentOutput(BaseModel):
    """A whole-result judgment, deliberately without per-claim verdicts or citations."""

    model_config = ConfigDict(extra="forbid")

    verdict: AssessmentVerdict
    rationale: str = Field(
        min_length=1,
        description="Explains the whole-result judgment using only the supplied saved material.",
    )
