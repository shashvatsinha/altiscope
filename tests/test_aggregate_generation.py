from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from altiscope.aggregate.generate import generate_aggregate
from altiscope.aggregate.inputs import ReportInput, render_inputs
from altiscope.aggregate.planner import estimate_aggregate_request_tokens
from altiscope.llm.provider import GenerationResult, Provider, Usage
from altiscope.schemas.aggregate import AggregateOutput, AggregateSection
from altiscope.summarize.fixture import FixtureProvider, fixture_registry

INPUTS = (
    ReportInput("pr", "review-1", "Calls acquire a lock.", ("https://github.com/o/r/pull/1",)),
)


def good_output() -> AggregateOutput:
    return AggregateOutput(
        headline="Thread safety",
        narrative="Calls now acquire a lock.",
        sections=[AggregateSection(heading="Concurrency", text="Added a lock.")],
    )


def generate(provider: Provider, budget: int = 10000):
    return generate_aggregate(
        provider,
        fixture_registry().models["fixture"],
        system="instructions",
        user="PR-1: lock",
        inputs=INPUTS,
        max_tokens=1000,
        effort="low",
        input_budget=budget,
    )


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        '{"headline":" "}',
        json.dumps({**good_output().model_dump(), "sources": ["unknown"]}),
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
    budget = estimate_aggregate_request_tokens("instructions", render_inputs("PR-1: lock", INPUTS))
    provider = FixtureProvider([])
    assert generate(provider, budget - 1).output is None
    assert provider.calls == 0
    provider = FixtureProvider(["not json"])
    result = generate(provider, budget)
    assert provider.calls == 1 and len(result.attempts) == 1
    assert result.output is None and "oversized_input" in result.errors[0]


def test_all_input_links_survive_multilevel_summarization_and_reruns():
    urls = tuple(f"https://github.com/o/r/pull/{i}" for i in range(1, 4))
    original = (
        ReportInput("pr", "review-1", "Calls acquire a lock.", (urls[0],)),
        ReportInput("pr", "review-2", "Billing retries failed jobs.", (urls[1],)),
    )

    def run(inputs: tuple[ReportInput, ...]):
        return generate_aggregate(
            FixtureProvider([good_output().model_dump_json()]),
            fixture_registry().models["fixture"],
            system="Summarize the supplied reports.",
            user="Explain this month's work.",
            inputs=inputs,
            max_tokens=1000,
            effort="low",
            input_budget=10000,
        )

    child = run(original)
    assert child.output is not None
    # The response discusses only locks, yet the billing PR remains available.
    assert child.pr_urls == urls[:2]
    assert child.inputs == original
    assert "Billing retries failed jobs." in child.attempts[0].user
    assert "review-2" not in child.attempts[0].user
    parent_inputs = (
        ReportInput("aggregate", "group-1", child.output.model_dump_json(), child.pr_urls),
        ReportInput("pr", "review-3", "Adds integration tests.", (urls[1], urls[2])),
    )
    parent = run(parent_inputs)
    assert parent.pr_urls == urls
    assert parent.inputs == parent_inputs

    updated = run((ReportInput("pr", "review-4", "Revised billing report.", (urls[1],)),))
    assert updated.inputs[0].report_version_id == "review-4"
    assert child.inputs == original
    assert parent.inputs[0].report_version_id == "group-1"
    # This exercises in-memory generation, not the future database version resolver.


def test_invalid_input_records_fail_before_model_call():
    provider = FixtureProvider([])
    for inputs in ((), INPUTS + INPUTS):
        with pytest.raises(ValueError):
            generate_aggregate(
                provider,
                fixture_registry().models["fixture"],
                system="instructions",
                user="Summarize",
                inputs=inputs,
                max_tokens=1000,
                effort="low",
                input_budget=10000,
            )
    assert provider.calls == 0
