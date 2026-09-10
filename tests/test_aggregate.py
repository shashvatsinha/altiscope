from __future__ import annotations

import pytest

from altiscope.aggregate.planner import PlanItem, PlanningError, plan_reduction


def _items(n: int, tokens: int = 1000) -> list[PlanItem]:
    return [
        PlanItem(order_key=(f"2026-06-{i:02d}", "alice"), id=f"s{i}", tokens=tokens)
        for i in range(1, n + 1)
    ]


def test_single_call_when_it_fits():
    node = plan_reduction(_items(10), budget_tokens=20_000)
    assert node.is_leaf and node.depth == 1 and node.call_count == 1
    assert [i.id for i in node.items] == [f"s{i}" for i in range(1, 11)]


def test_two_level_tree_when_it_does_not_fit():
    node = plan_reduction(
        _items(10), budget_tokens=4_200, per_item_overhead=50, child_output_tokens=1_000
    )
    assert not node.is_leaf
    assert node.depth == 2
    assert node.leaf_count == 3  # 4 + 4 + 2 items at 1050 each under 4200
    assert node.call_count == 4
    assert [i.id for i in node.children[0].items] == ["s1", "s2", "s3", "s4"]


def test_three_level_tree_for_many_inputs():
    node = plan_reduction(
        _items(100), budget_tokens=4_200, per_item_overhead=50, child_output_tokens=500
    )
    assert node.depth == 3
    assert node.leaf_count == 25


def test_ordering_is_deterministic_regardless_of_input_order():
    items = _items(9)
    a = plan_reduction(list(reversed(items)), budget_tokens=3_500, child_output_tokens=1_000)
    b = plan_reduction(items, budget_tokens=3_500, child_output_tokens=1_000)
    assert [[i.id for i in c.items] for c in a.children] == [
        [i.id for i in c.items] for c in b.children
    ]


def test_unreducible_tree_is_an_error():
    with pytest.raises(PlanningError, match="fewer than two child summaries"):
        plan_reduction(_items(10), budget_tokens=4_200, child_output_tokens=4_000)


def test_item_larger_than_budget_is_an_error():
    with pytest.raises(PlanningError, match="needs 1,050 tokens; budget is 1,000"):
        plan_reduction(_items(2), budget_tokens=1_000)


def test_empty_input_is_an_error():
    with pytest.raises(PlanningError):
        plan_reduction([], budget_tokens=1_000)


def test_altitude_parsing_and_aliases():
    from altiscope.schemas.aggregate import Altitude

    assert Altitude.from_str("ic") == Altitude.ic
    assert Altitude.from_str("engineer") == Altitude.ic
    assert Altitude.from_str("dev") == Altitude.ic
    assert Altitude.from_str("manager") == Altitude.manager
    assert Altitude.from_str("lead") == Altitude.manager
    assert Altitude.from_str("exec") == Altitude.exec
    assert Altitude.from_str("executive") == Altitude.exec
    assert Altitude.from_str("director") == Altitude.exec

    with pytest.raises(ValueError):
        Altitude.from_str("unknown_altitude")


def test_aggregate_prompt_v4_loaded_as_latest():
    from altiscope.prompts import latest_prompt
    from tests.conftest import REPO_ROOT

    prompt = latest_prompt(REPO_ROOT / "prompts", "aggregate")
    assert prompt.version == "v4"
    assert prompt.schema_version == 4
    assert prompt.stage == "aggregate"
    assert "Describe work, never people" in prompt.body
    assert "The application" in prompt.body
    assert "ic: Peer engineers" in prompt.body
    assert "manager: Engineering managers" in prompt.body
    assert "exec: Executive leadership" in prompt.body


def test_aggregate_schema_v4_forbids_extra_fields():
    import pydantic

    from altiscope.schemas.aggregate import AGGREGATE_SCHEMA_VERSION, AggregateOutput

    assert AGGREGATE_SCHEMA_VERSION == 4
    payload = {
        "headline": "New billing pipeline",
        "sections": [{"heading": "Billing", "text": "Added retries"}],
        "narrative": "Billing pipeline now retries on failure.",
    }
    parsed = AggregateOutput.model_validate(payload)
    assert parsed.headline == "New billing pipeline"

    with pytest.raises(pydantic.ValidationError):
        AggregateOutput.model_validate({**payload, "sources": ["PR-1"]})


def test_aggregate_budgeting_and_request_token_estimation():
    from altiscope.aggregate.planner import (
        calculate_aggregate_input_budget,
        estimate_aggregate_request_tokens,
    )

    budget = calculate_aggregate_input_budget(
        1_000_000,
        budget_fraction=0.75,
        reserved_output_tokens=16_000,
        system_prompt_tokens=1_000,
        overhead_tokens=256,
        schema_tokens=500,
    )
    # 750,000 - 16,000 - 1,000 - 256 - 500 = 732,244
    assert budget == 732_244

    with pytest.raises(PlanningError, match="No input budget"):
        calculate_aggregate_input_budget(10_000, budget_fraction=0.5, reserved_output_tokens=10_000)
    assert (
        calculate_aggregate_input_budget(
            1000,
            budget_fraction=1,
            reserved_output_tokens=100,
            system_prompt_tokens=100,
            overhead_tokens=100,
            schema_tokens=200,
        )
        == 500
    )

    tokens = estimate_aggregate_request_tokens("system prompt", "user prompt with PR summaries")
    assert tokens > 0
