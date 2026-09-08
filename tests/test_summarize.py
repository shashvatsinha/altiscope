from __future__ import annotations

from altiscope.ingest.diff_policy import apply
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.summarize.context import render_user_prompt
from altiscope.summarize.facts import compute_facts
from altiscope.summarize.service import prepare


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


def test_context_shows_code_before_prose_and_discloses_omissions(snapshot: PullRequestSnapshot):
    ctx = prepare(snapshot)
    prompt = render_user_prompt(ctx)
    assert "<comment kind=review author=bob on app/main.py:3>" in prompt
    assert "# 3. Code changes (primary evidence)" in prompt
    assert prompt.index("# 4. Patches of included files") < prompt.index(
        "# 5. Pull request context"
    )
    assert "package-lock.json [lockfile] +400/-380" in prompt
    assert "<file path='app/main.py'>" in prompt


def test_comments_with_shared_id_are_preserved_in_stable_order(snapshot: PullRequestSnapshot):
    snapshot.comments[1].github_id = snapshot.comments[0].github_id
    expected = render_user_prompt(prepare(snapshot))
    snapshot.comments.reverse()
    actual = render_user_prompt(prepare(snapshot))
    assert actual == expected
    assert actual.count("Should this lock be re-entrant?") == 1
    assert actual.count("Added the test you asked for.") == 1
    assert actual.index("Should this lock be re-entrant?") < actual.index(
        "Added the test you asked for."
    )
    assert "kind=review author=bob on app/main.py:3" in actual
    assert "kind=issue author=alice" in actual
