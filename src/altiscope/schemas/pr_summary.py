"""Atomic per-PR summary: what the model emits for one merged pull request.

The model never sees database ids. Review comments are referred to by per-call opaque
tokens (see altiscope.summarize.context); files by path; commits by sha prefix. Every
pointer is validated against the stored snapshot before the summary is stored.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

PR_SUMMARY_SCHEMA_VERSION = 1


class ClaimKind(StrEnum):
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


class EvidenceType(StrEnum):
    file = "file"
    hunk = "hunk"
    description = "description"
    pr_title = "title"  # `title` would shadow str.title on a StrEnum
    review_comment = "review_comment"
    commit = "commit"


class Evidence(BaseModel):
    """One checkable pointer into the PR snapshot."""

    model_config = ConfigDict(extra="forbid")

    type: EvidenceType
    path: str | None = Field(default=None, description="File path, for file/hunk evidence.")
    hunk_header: str | None = Field(
        default=None, description='The "@@ -a,b +c,d @@" line, for hunk evidence.'
    )
    quote: str | None = Field(
        default=None, description="Verbatim span, for description/title evidence."
    )
    comment_id: str | None = Field(
        default=None, description="Opaque comment token as shown in the material."
    )
    commit_sha: str | None = Field(default=None, description="Commit sha prefix (7+ chars).")

    @model_validator(mode="after")
    def _shape_matches_type(self) -> Evidence:
        required: dict[EvidenceType, tuple[str, ...]] = {
            EvidenceType.file: ("path",),
            EvidenceType.hunk: ("path", "hunk_header"),
            EvidenceType.description: ("quote",),
            EvidenceType.pr_title: ("quote",),
            EvidenceType.review_comment: ("comment_id",),
            EvidenceType.commit: ("commit_sha",),
        }
        for field in required[self.type]:
            if not getattr(self, field):
                msg = f"evidence of type {self.type.value} requires {field}"
                raise ValueError(msg)
        return self


class Claim(BaseModel):
    """One atomic, checkable statement about what the PR changed."""

    model_config = ConfigDict(extra="forbid")

    kind: ClaimKind
    text: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class Discrepancy(BaseModel):
    """A place where the description and the diff disagree."""

    model_config = ConfigDict(extra="forbid")

    description_says: str = Field(min_length=1)
    diff_shows: str = Field(min_length=1)


class PrSummaryOutput(BaseModel):
    """The structured output of the pr_summary stage."""

    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1, description="One sentence: what changed.")
    claims: list[Claim] = Field(min_length=1)
    description_vs_diff: list[Discrepancy] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    narrative: str = Field(min_length=1, description="Composed only from the claims above.")
