from __future__ import annotations

from unittest.mock import Mock

import pytest

from altiscope.aggregate.generate import generate_aggregate
from altiscope.aggregate.planner import estimate_aggregate_request_tokens
from altiscope.llm.provider import GenerationResult, Provider, Usage
from altiscope.schemas.aggregate import AggregateOutput, AggregateSection
from altiscope.summarize.fixture import FixtureProvider, fixture_registry


def good_output() -> AggregateOutput:
    return AggregateOutput(
        headline="Thread safety",
        narrative="Calls now acquire a lock.",
        sections=[AggregateSection(heading="Concurrency", text="Added a lock.")],
        sources=["PR-1"],
    )


def generate(provider: Provider, budget: int = 10000):
    return generate_aggregate(
        provider,
        fixture_registry().models["fixture"],
        system="instructions",
        user="PR-1: lock",
        allowed_sources={"PR-1"},
        max_tokens=1000,
        effort="low",
        input_budget=budget,
    )


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        '{"headline":" "}',
        good_output().model_copy(update={"sources": ["unknown"]}).model_dump_json(),
    ],
)
def test_single_replacement_and_failed_repair(bad: str):
    good = good_output().model_dump_json()
    provider = FixtureProvider([bad, good])
    repaired = generate(provider)
    assert provider.calls == 2 and repaired.output == good_output()
    assert repaired.attempts[0].errors and not repaired.attempts[1].errors
    provider = FixtureProvider([bad, bad, good])
    failed = generate(provider)
    assert provider.calls == 2 and failed.output is None and failed.errors


@pytest.mark.parametrize("reason", ["refusal", "max_tokens", "transport_error", "unknown"])
def test_terminal_outcomes_are_not_repaired_or_published(reason: str):
    result = GenerationResult(
        parsed=good_output(),
        raw_text="partial",
        model_id="fixture",
        stop_reason=reason,
        usage=Usage(1, 1),
        latency_ms=1,
        output_mode="native",
    )
    provider = Mock()
    provider.generate_structured.return_value = result
    generated = generate(provider)
    assert generated.output is None and generated.errors == (reason,)
    assert provider.generate_structured.call_count == 1


def test_complete_request_and_repair_budget_checked_before_each_call():
    budget = estimate_aggregate_request_tokens("instructions", "PR-1: lock")
    provider = FixtureProvider([])
    assert generate(provider, budget - 1).output is None
    assert provider.calls == 0
    provider = FixtureProvider(["not json"])
    result = generate(provider, budget)
    assert provider.calls == 1 and len(result.attempts) == 1
    assert result.output is None and "oversized_input" in result.errors[0]
