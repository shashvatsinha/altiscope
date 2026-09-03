"""In-memory shape of a PR snapshot as fetched from GitHub, before storage.

Mirrors the pull_requests / pr_files / pr_commits / pr_reviews / pr_comments tables.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PrState(StrEnum):
    open = "open"
    closed = "closed"
    merged = "merged"


class FileStatus(StrEnum):
    added = "added"
    modified = "modified"
    removed = "removed"
    renamed = "renamed"
    copied = "copied"
    changed = "changed"
    unchanged = "unchanged"


class PrFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    previous_path: str | None = None
    status: FileStatus
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    patch: str | None = None  # None when GitHub omits it (binary or oversize)
    is_binary: bool = False


class PrCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha: str = Field(min_length=7)
    message: str
    author_login: str | None = None
    authored_at: datetime | None = None


class ReviewState(StrEnum):
    approved = "APPROVED"
    changes_requested = "CHANGES_REQUESTED"
    commented = "COMMENTED"
    dismissed = "DISMISSED"
    pending = "PENDING"


class PrReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    github_id: int
    author_login: str
    state: ReviewState
    body: str = ""
    submitted_at: datetime | None = None


class CommentKind(StrEnum):
    issue = "issue"  # PR conversation
    review = "review"  # inline on the diff


class PrComment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    github_id: int
    kind: CommentKind
    author_login: str
    body: str
    created_at: datetime
    path: str | None = None
    line: int | None = None
    in_reply_to_github_id: int | None = None


class PullRequestSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(description="owner/name")
    number: int
    github_id: int
    title: str
    body: str = ""
    author_login: str
    state: PrState
    is_draft: bool = False
    base_ref: str
    head_ref: str
    merge_commit_sha: str | None = None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    merged_at: datetime | None = None
    merged_by_login: str | None = None
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    changed_files: int = Field(ge=0)
    labels: list[str] = Field(default_factory=list)
    html_url: str
    files: list[PrFile] = Field(default_factory=list)
    commits: list[PrCommit] = Field(default_factory=list)
    reviews: list[PrReview] = Field(default_factory=list)
    comments: list[PrComment] = Field(default_factory=list)
