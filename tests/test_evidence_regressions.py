from __future__ import annotations

import pytest

from altiscope.ingest.snapshot import CommentKind, PrCommit, PullRequestSnapshot
from altiscope.schemas.pr_summary import Evidence, EvidenceType
from altiscope.summarize.context import render_user_prompt
from altiscope.summarize.validate import validate_summary
from tests.test_summarize import good_output, make_context


@pytest.mark.parametrize(
    "evidence",
    [
        Evidence(type=EvidenceType.commit, commit_sha="1"),
        Evidence(type=EvidenceType.commit, commit_sha="xxxxxxx"),
        Evidence(type=EvidenceType.description, quote=" \n\t"),
        Evidence(type=EvidenceType.pr_title, quote=" "),
        Evidence(type=EvidenceType.description, quote="wraps run()"),
        Evidence(type=EvidenceType.hunk, path="app/main.py", hunk_header="+import threading"),
    ],
)
def test_invalid_evidence_is_rejected(snapshot: PullRequestSnapshot, evidence: Evidence):
    output = good_output()
    output.claims[0].evidence = [evidence]
    assert not validate_summary(output, make_context(snapshot)).ok


def test_commit_prefix_must_be_unique(snapshot: PullRequestSnapshot):
    snapshot.commits.append(PrCommit(sha="1111111bbbbbbb", message="another commit"))
    assert not validate_summary(good_output(), make_context(snapshot)).ok


def test_comment_ids_are_scoped_by_kind(snapshot: PullRequestSnapshot):
    snapshot.comments[1].github_id = snapshot.comments[0].github_id
    ctx = make_context(snapshot)
    assert ctx.comment_tokens == {"c1": (CommentKind.review, 501), "c2": (CommentKind.issue, 501)}
    text = render_user_prompt(ctx)
    assert text.count("Should this lock be re-entrant?") == 1
    assert text.count("Added the test you asked for.") == 1


def test_quotes_collapse_whitespace_but_preserve_case(snapshot: PullRequestSnapshot):
    output = good_output()
    output.claims[0].evidence = [
        Evidence(type=EvidenceType.description, quote="Wraps\nrun() in a lock"),
        Evidence(type=EvidenceType.file, path="app/main.py", quote="def run()"),
    ]
    assert validate_summary(output, make_context(snapshot)).ok
