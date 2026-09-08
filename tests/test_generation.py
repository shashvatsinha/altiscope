from __future__ import annotations

from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.llm.registry import Registry
from altiscope.schemas.pr_summary import PrAccountOutput
from altiscope.summarize.fixture import FixtureProvider
from altiscope.summarize.generate import generate_account, request_tokens
from altiscope.summarize.publication import PublicationState
from tests.conftest import REPO_ROOT
from tests.test_summarize import good_output, make_context


def generate(snapshot: PullRequestSnapshot, responses: list[str], budget: int = 100000):
    registry = Registry.load(REPO_ROOT / "config/models.yaml")
    model = registry.models[registry.stages["pr_summary"].candidates[0]]
    provider = FixtureProvider(responses)
    result = generate_account(
        make_context(snapshot),
        provider,
        model,
        system="instructions",
        max_tokens=1000,
        effort="low",
        input_budget=budget,
    )
    return result, provider


def test_repair_once_and_withhold_all_bad_claims(snapshot: PullRequestSnapshot):
    good = PrAccountOutput(claims=good_output().claims).model_dump_json()
    bad = good.replace("app/main.py", "unknown.py")
    repaired, provider = generate(snapshot, [bad, good])
    assert provider.calls == 2
    assert repaired.publication.state == PublicationState.citation_valid
    assert repaired.attempts[0].errors
    failed, provider = generate(snapshot, [bad, bad, good])
    assert provider.calls == 2
    assert failed.publication.output is None
    assert failed.publication.state == PublicationState.needs_review


def test_full_request_budget_prevents_call(snapshot: PullRequestSnapshot):
    result, provider = generate(snapshot, [], budget=1)
    assert provider.calls == 0
    assert "oversized_input" in result.publication.errors[0]
    assert request_tokens("", "") > 256  # Output schema must be counted.
