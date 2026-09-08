from __future__ import annotations

from altiscope.ingest.diff_policy import apply, manifest
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.schemas.pr_summary import Claim, ClaimKind, Evidence, EvidenceType, PrSummaryOutput
from altiscope.summarize.context import PrContext, build_context, render_user_prompt
from altiscope.summarize.facts import compute_facts
from altiscope.summarize.validate import lint_language, validate_summary


def make_context(snapshot: PullRequestSnapshot) -> PrContext:
    outcome = apply(snapshot.files)
    facts = compute_facts(snapshot, outcome)
    return build_context(snapshot, outcome, facts, manifest(outcome))


def good_output() -> PrSummaryOutput:
    return PrSummaryOutput(
        headline="run() now takes a lock",
        claims=[
            Claim(
                kind=ClaimKind.bugfix,
                text="run() acquires a module-level lock.",
                evidence=[
                    Evidence(
                        type=EvidenceType.hunk, path="app/main.py", hunk_header="@@ -1,4 +1,6 @@"
                    ),
                    Evidence(type=EvidenceType.description, quote="Wraps run() in a lock"),
                ],
            ),
            Claim(
                kind=ClaimKind.test,
                text="A test for run() was added.",
                evidence=[
                    Evidence(type=EvidenceType.file, path="tests/test_main.py"),
                    Evidence(type=EvidenceType.review_comment, comment_id="c2"),
                    Evidence(type=EvidenceType.commit, commit_sha="1111111"),
                ],
            ),
        ],
        narrative="run() acquires a lock; a test was added.",
    )


def test_facts_are_computed_from_snapshot(snapshot: PullRequestSnapshot):
    facts = compute_facts(snapshot, apply(snapshot.files))
    assert facts.files_changed == 3
    assert facts.included_files == 2 and facts.excluded_files == 1
    assert facts.languages == {"Python": 2}
    assert facts.test_files_touched == ["tests/test_main.py"]
    assert [r.login for r in facts.reviewers] == ["bob"]
    assert facts.reviewers[0].final_state == "APPROVED" and facts.reviewers[0].review_count == 2
    assert facts.changes_requested_rounds == 1
    assert facts.review_comment_count == 1 and facts.conversation_comment_count == 1
    assert facts.time_to_merge_hours == 5.0
    assert facts.linked_issues == [17]


def test_context_assigns_opaque_comment_tokens_in_time_order(snapshot: PullRequestSnapshot):
    ctx = make_context(snapshot)
    assert ctx.comment_tokens == {"c1": ("review", 501), "c2": ("issue", 502)}
    prompt = render_user_prompt(ctx)
    assert "<comment id=c1 kind=review author=bob on app/main.py:3>" in prompt
    assert "# 3. Code changes (primary evidence)" in prompt
    assert prompt.index("# 4. Patches of included files") < prompt.index(
        "# 5. Pull request context"
    )
    assert "package-lock.json [lockfile] +400/-380" in prompt
    assert "<file path='app/main.py'>" in prompt
    assert "501" not in prompt.split("# 6.")[1]  # no GitHub ids leak into the material


def test_valid_summary_passes(snapshot: PullRequestSnapshot):
    result = validate_summary(good_output(), make_context(snapshot))
    assert result.ok, result.errors
    assert result.warnings == []


def test_bad_pointers_are_rejected(snapshot: PullRequestSnapshot):
    out = good_output()
    out.claims[0].evidence = [
        Evidence(type=EvidenceType.file, path="package-lock.json"),
        Evidence(type=EvidenceType.file, path="does/not/exist.py"),
        Evidence(type=EvidenceType.hunk, path="app/main.py", hunk_header="@@ -9,9 +9,9 @@"),
        Evidence(type=EvidenceType.description, quote="rewrites the scheduler"),
        Evidence(type=EvidenceType.pr_title, quote="thread-safe"),
        Evidence(type=EvidenceType.review_comment, comment_id="c9"),
        Evidence(type=EvidenceType.commit, commit_sha="deadbeef"),
    ]
    result = validate_summary(out, make_context(snapshot))
    assert not result.ok
    assert len(result.errors) == 6
    assert any("excluded from the material" in e for e in result.errors)
    assert any("not in the material" in e for e in result.errors)
    assert any("hunk" in e for e in result.errors)
    assert any("quote not found in description" in e for e in result.errors)
    assert any("unknown comment id 'c9'" in e for e in result.errors)
    assert any("unknown commit 'deadbeef'" in e for e in result.errors)


def test_evaluative_language_is_a_warning_not_an_error(snapshot: PullRequestSnapshot):
    out = good_output()
    out.narrative = "An impressive fix; alice was very productive."
    result = validate_summary(out, make_context(snapshot))
    assert result.ok
    assert len(result.warnings) == 2
    assert lint_language("fast path for cache hits") == []


def test_evidence_shape_is_enforced():
    import pytest

    with pytest.raises(ValueError, match="requires hunk_header"):
        Evidence(type=EvidenceType.hunk, path="a.py")
    with pytest.raises(ValueError, match="requires quote"):
        Evidence(type=EvidenceType.description)
