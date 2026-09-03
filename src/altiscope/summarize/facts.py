"""Facts computed in code from the snapshot. The model is given these; it never derives them."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from altiscope.ingest.diff_policy import PolicyOutcome
from altiscope.ingest.snapshot import PullRequestSnapshot, ReviewState

_TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs)(/|$)|(_test\.|\.test\.|\.spec\.|^test_|/test_|_spec\.)",
)
_ISSUE_REF_RE = re.compile(r"(?<![\w/])#(\d+)\b|github\.com/[\w.-]+/[\w.-]+/issues/(\d+)")

_EXT_LANGUAGE: dict[str, str] = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sql": "SQL",
    ".sh": "Shell",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".md": "Markdown",
    ".tf": "Terraform",
    ".proto": "Protobuf",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
}


class ReviewerFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str
    final_state: str
    review_count: int


class PrFacts(BaseModel):
    """Stored as pr_summaries.facts. Rendered from data in the UI."""

    model_config = ConfigDict(extra="forbid")

    files_changed: int
    additions: int
    deletions: int
    included_files: int
    excluded_files: int
    languages: dict[str, int] = Field(description="file count per language, included files")
    test_files_touched: list[str]
    commit_count: int
    reviewers: list[ReviewerFact]
    changes_requested_rounds: int
    review_comment_count: int
    conversation_comment_count: int
    time_to_merge_hours: float | None
    labels: list[str]
    linked_issues: list[int]
    is_draft: bool
    base_ref: str


def _language(path: str) -> str | None:
    return _EXT_LANGUAGE.get(PurePosixPath(path).suffix.lower())


def compute_facts(snapshot: PullRequestSnapshot, outcome: PolicyOutcome) -> PrFacts:
    included_paths = [d.path for d in outcome.included]
    languages = Counter(lang for p in included_paths if (lang := _language(p)) is not None)

    by_reviewer: dict[str, list[ReviewState]] = {}
    for review in snapshot.reviews:
        if review.author_login == snapshot.author_login:
            continue
        by_reviewer.setdefault(review.author_login, []).append(review.state)
    reviewers = [
        ReviewerFact(login=login, final_state=states[-1].value, review_count=len(states))
        for login, states in sorted(by_reviewer.items())
    ]

    time_to_merge: float | None = None
    if snapshot.merged_at is not None:
        time_to_merge = round((snapshot.merged_at - snapshot.created_at).total_seconds() / 3600, 2)

    issues: set[int] = set()
    for match in _ISSUE_REF_RE.finditer(snapshot.body):
        number = match.group(1) or match.group(2)
        issues.add(int(number))

    return PrFacts(
        files_changed=len(snapshot.files),
        additions=snapshot.additions,
        deletions=snapshot.deletions,
        included_files=len(outcome.included),
        excluded_files=len(outcome.excluded),
        languages=dict(sorted(languages.items())),
        test_files_touched=sorted(p for p in included_paths if _TEST_PATH_RE.search(p)),
        commit_count=len(snapshot.commits),
        reviewers=reviewers,
        changes_requested_rounds=sum(
            1 for r in snapshot.reviews if r.state is ReviewState.changes_requested
        ),
        review_comment_count=sum(1 for c in snapshot.comments if c.kind.value == "review"),
        conversation_comment_count=sum(1 for c in snapshot.comments if c.kind.value == "issue"),
        time_to_merge_hours=time_to_merge,
        labels=sorted(snapshot.labels),
        linked_issues=sorted(issues),
        is_draft=snapshot.is_draft,
        base_ref=snapshot.base_ref,
    )
