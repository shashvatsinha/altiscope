import pytest
from pydantic import ValidationError

from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.schemas.pr_summary import PrReviewOutput
from altiscope.summarize.publication import Publication, PublicationState, assess, render_account
from tests.test_summarize import make_context


def test_review_needs_no_citations_and_links_to_pr(snapshot: PullRequestSnapshot):
    output = PrReviewOutput(
        review="The patch adds locking. Its test does not exercise concurrency."
    )
    ctx = make_context(snapshot)
    publication = assess(output, ctx)
    report = render_account(publication, ctx)
    assert publication.state == PublicationState.published
    assert output.review in report
    assert snapshot.html_url in report
    assert f"{snapshot.repository}#{snapshot.number}" in report
    assert "interpretation unverified" in report
    assert "Input omissions:" in report
    assert "Computed facts:" in render_account(publication, ctx, verbose=True)


@pytest.mark.parametrize("value", ["", " \n\t"])
def test_empty_review_rejected(value: str):
    with pytest.raises(ValidationError):
        PrReviewOutput(review=value)


def test_model_cannot_supply_provenance():
    with pytest.raises(ValidationError):
        PrReviewOutput.model_validate({"review": "Some changes", "pr_url": "invented"})


def test_failed_review_displays_reason(snapshot: PullRequestSnapshot):
    publication = Publication(PublicationState.needs_review, None, ("max_tokens",))
    report = render_account(publication, make_context(snapshot))
    assert "Reason: max_tokens" in report
    assert "Generated review unavailable" in report
