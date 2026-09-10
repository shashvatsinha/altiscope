from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from altiscope.aggregate.inputs import ReportInput, render_inputs
from altiscope.aggregate.planner import estimate_aggregate_request_tokens
from altiscope.aggregate.service import (
    AggregateError,
    AggregateQuery,
    MemoryAggregateStore,
    aggregate_reports,
)
from altiscope.llm.router import RoutingError
from altiscope.prompts import latest_prompt
from altiscope.schemas.aggregate import Altitude
from altiscope.summarize.fixture import FixtureProvider, fixture_registry
from tests.conftest import REPO_ROOT
from tests.test_aggregate_generation import good_output


@pytest.fixture
def query():
    return AggregateQuery(
        repository="o/r",
        since=datetime(2026, 6, 1, tzinfo=UTC),
        until=datetime(2026, 6, 30, tzinfo=UTC),
        altitude=Altitude.manager,
    )


def sample_inputs(n: int = 4):
    return tuple(
        ReportInput(
            "pr",
            str(i),
            "A changed module. " * 100,
            (f"https://github.com/o/r/pull/{i}",),
            f"snapshot-{i}",
        )
        for i in range(n)
    )


def test_tree_execution_cache_history_and_failed_rerun(query: AggregateQuery):
    inputs = sample_inputs()
    registry = fixture_registry()
    registry.input_budget_fraction = 1
    registry.stages["aggregate"].reserved_output_tokens = 200
    prompt = latest_prompt(REPO_ROOT / "prompts", "aggregate")
    size = estimate_aggregate_request_tokens(
        prompt.body, render_inputs(query.instruction(), inputs[:2])
    )
    registry.models["fixture"].context_window = size + 200 + 32
    store = MemoryAggregateStore()
    good = good_output().model_dump_json()

    def run(provider: FixtureProvider, *, force: bool = False):
        return aggregate_reports(
            inputs,
            query=query,
            store=store,
            registry=registry,
            prompt=prompt,
            provider=provider,
            force=force,
        )

    result = run(FixtureProvider([good] * 3))
    assert result.calls == 3 and result.report is not None
    assert len(store.reports) == 3
    assert all(item.kind == "aggregate" for item in result.report.inputs)
    assert len(result.report.pr_urls) == 4
    cached = run(FixtureProvider([]))
    assert cached.calls == 0 and cached.cache_hits == 3
    assert cached.report == result.report
    # A forced rerun that fails after a completed child retains old publications.
    with pytest.raises(AggregateError):
        run(FixtureProvider([good, "invalid", "invalid"]), force=True)
    assert store.get(result.report.id) == result.report
    # A new valid child version is now the default input to the next requested parent.
    updated = run(FixtureProvider([good]))
    assert updated.calls == 1 and updated.report != result.report
    assert store.get(result.report.id).inputs == result.report.inputs


@pytest.mark.parametrize(
    "change", ["review", "source", "version", "prompt", "model", "altitude", "effort"]
)
def test_cache_distinguishes_input_and_generation_changes(query: AggregateQuery, change: str):
    inputs = sample_inputs(1)
    registry = fixture_registry()
    prompt = latest_prompt(REPO_ROOT / "prompts", "aggregate")
    store = MemoryAggregateStore()
    good = good_output().model_dump_json()
    first = aggregate_reports(
        inputs,
        query=query,
        store=store,
        registry=registry,
        prompt=prompt,
        provider=FixtureProvider([good]),
    )
    if change == "review":
        inputs = (replace(inputs[0], text="Revised review"),)
    if change == "source":
        inputs = (replace(inputs[0], source_hash="changed-source"),)
    if change == "version":
        inputs = (replace(inputs[0], report_version_id="new-version"),)
    if change == "prompt":
        prompt = replace(prompt, content_hash="new-prompt", body="Revised instructions")
    if change == "model":
        registry.models["fixture"].model_name = "different-model"
    if change == "altitude":
        query = query.model_copy(update={"altitude": Altitude.ic})
    if change == "effort":
        registry.stages["aggregate"].effort = "high"
    changed = aggregate_reports(
        inputs,
        query=query,
        store=store,
        registry=registry,
        prompt=prompt,
        provider=FixtureProvider([good]),
    )
    assert changed.calls == 1 and changed.report is not None and first.report is not None
    assert changed.report.input_hash != first.report.input_hash
    assert len(store.reports) == 2


def test_empty_and_actual_parent_budget(query: AggregateQuery):
    registry = fixture_registry()
    prompt = latest_prompt(REPO_ROOT / "prompts", "aggregate")
    store = MemoryAggregateStore()
    result = aggregate_reports(
        (), query=query, store=store, registry=registry, prompt=prompt, provider=FixtureProvider([])
    )
    assert result.report is None and result.calls == 0 and not store.reports
    inputs = sample_inputs()
    registry.input_budget_fraction = 1
    registry.stages["aggregate"].reserved_output_tokens = 200
    registry.models["fixture"].context_window = (
        estimate_aggregate_request_tokens(
            prompt.body, render_inputs(query.instruction(), inputs[:2])
        )
        + 232
    )
    # A provider can return more text than the configured reservation. Check actual children.
    oversized = (
        good_output().model_copy(update={"narrative": "very long " * 5000}).model_dump_json()
    )
    provider = FixtureProvider([oversized, oversized])
    with pytest.raises(RoutingError):
        aggregate_reports(
            inputs, query=query, store=store, registry=registry, prompt=prompt, provider=provider
        )
    assert provider.calls == 2  # No oversized parent request was sent.


def test_multiple_models_route_complete_requests(query: AggregateQuery):
    registry = fixture_registry()
    registry.models["small"] = registry.models["fixture"].model_copy(
        update={"id": "small", "context_window": 5000}
    )
    registry.stages["aggregate"].candidates = ["small", "fixture"]
    store = MemoryAggregateStore()
    result = aggregate_reports(
        sample_inputs(1),
        query=query,
        store=store,
        registry=registry,
        prompt=latest_prompt(REPO_ROOT / "prompts", "aggregate"),
        provider=FixtureProvider([good_output().model_dump_json()]),
    )
    assert result.report and result.report.model_id == "fixture"


def test_three_level_execution_keeps_all_original_prs(query: AggregateQuery):
    registry = fixture_registry()
    prompt = latest_prompt(REPO_ROOT / "prompts", "aggregate")
    inputs = sample_inputs(30)
    registry.input_budget_fraction = 1
    registry.stages["aggregate"].reserved_output_tokens = 200
    registry.models["fixture"].context_window = (
        estimate_aggregate_request_tokens(
            prompt.body, render_inputs(query.instruction(), inputs[:2])
        )
        + 232
    )
    store = MemoryAggregateStore()
    result = aggregate_reports(
        inputs,
        query=query,
        store=store,
        registry=registry,
        prompt=prompt,
        provider=FixtureProvider([good_output().model_dump_json()] * 100),
    )
    assert result.report and len(result.report.pr_urls) == 30
    assert any(
        store.get(i.report_version_id).inputs[0].kind == "aggregate" for i in result.report.inputs
    )
    repeated = aggregate_reports(
        inputs,
        query=query,
        store=store,
        registry=registry,
        prompt=prompt,
        provider=FixtureProvider([]),
    )
    assert repeated.calls == 0 and repeated.report == result.report
