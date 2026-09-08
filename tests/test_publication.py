import pytest
from pydantic import ValidationError

from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.schemas.pr_summary import PrAccountOutput
from altiscope.summarize.publication import PublicationState, assess, render_account
from tests.test_summarize import good_output, make_context


def test_no_prose_bypass(snapshot: PullRequestSnapshot):
    legacy = good_output().model_dump()
    with pytest.raises(ValidationError):
        PrAccountOutput.model_validate(legacy)
    output = PrAccountOutput(claims=good_output().claims)
    ctx = make_context(snapshot)
    result = assess(output, ctx)
    assert result.state == PublicationState.citation_valid
    assert "interpretation unverified" in render_account(result, ctx)
    concise = render_account(result, ctx)
    assert "Evidence:" not in concise
    assert "Computed facts:" not in concise
    assert "run() acquires a module-level lock." in concise
    detailed = render_account(result, ctx, verbose=True)
    assert "Evidence:" in detailed
    assert "Computed facts:" in detailed
    output.claims[0].evidence[0].path = "unknown.py"
    report = render_account(result, ctx)
    assert "withheld" in report
    assert output.claims[0].text not in report
    assert output.claims[1].text not in report


def test_language_warning_withholds_account(snapshot: PullRequestSnapshot):
    output = PrAccountOutput(claims=good_output().claims)
    output.claims[0].text = "Alice did excellent work."
    assert assess(output, make_context(snapshot)).state == PublicationState.needs_review


def test_description_only_claim_is_withheld(snapshot: PullRequestSnapshot):
    output = PrAccountOutput.model_validate(
        {
            "claims": [
                {
                    "kind": "bugfix",
                    "text": "The PR fixes a race.",
                    "evidence": [{"type": "description", "quote": "Wraps run() in a lock"}],
                }
            ]
        }
    )
    publication = assess(output, make_context(snapshot))
    assert publication.state == PublicationState.needs_review
    assert "prose alone" in publication.errors[0]
