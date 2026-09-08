from __future__ import annotations

import pytest

from altiscope.aggregate.coverage import compute_coverage
from altiscope.aggregate.planner import PlanItem, PlanningError, plan_reduction
from altiscope.aggregate.validate import validate_aggregate
from altiscope.schemas.aggregate import AggregateClaim, AggregateClaimKind, AggregateOutput


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


def _output(*sources_per_claim: list[str]) -> AggregateOutput:
    return AggregateOutput(
        headline="h",
        claims=[
            AggregateClaim(kind=AggregateClaimKind.theme, text=f"claim {i}", sources=s)
            for i, s in enumerate(sources_per_claim)
        ],
        narrative="n",
    )


def test_unknown_sources_are_dropped_or_trimmed():
    v = validate_aggregate(
        _output(["k1", "k2"], ["k9"], ["k3", "k8", "k3"]), allowed_sources={"k1", "k2", "k3"}
    )
    assert not v.ok
    assert [c.sources for c in v.output.claims] == [["k1", "k2"], ["k3"]]
    assert [d.unknown_sources for d in v.dropped] == [["k9"]]
    assert v.trimmed_sources == 1


def test_all_claims_invalid_is_fatal():
    with pytest.raises(ValueError, match="every aggregate claim"):
        validate_aggregate(_output(["zz"]), allowed_sources={"k1"})


def test_coverage_names_uncited_inputs():
    source_to_input = {"k1": "s1", "k2": "s1", "k3": "s2", "k4": "s3"}
    cov = compute_coverage(
        {"s1", "s2", "s3", "s4"}, _output(["k1"], ["k3"]).claims, source_to_input
    )
    assert cov.input_count == 4 and cov.cited_count == 2
    assert cov.cited == ["s1", "s2"]
    assert cov.uncited == ["s3", "s4"]
    assert cov.ratio == 0.5
    assert cov.is_low()
    assert not cov.is_low(threshold=0.5)


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


def test_aggregate_prompt_v2_loaded_as_latest():
    from altiscope.prompts import latest_prompt
    from tests.conftest import REPO_ROOT

    prompt = latest_prompt(REPO_ROOT / "prompts", "aggregate")
    assert prompt.version == "v2"
    assert prompt.schema_version == 2
    assert prompt.stage == "aggregate"
    assert "Describe work, never people" in prompt.body
    assert "PR-42" in prompt.body
    assert "ic: Peer engineers" in prompt.body
    assert "manager: Engineering managers" in prompt.body
    assert "exec: Executive leadership" in prompt.body


def test_aggregate_schema_v2_forbids_extra_fields():
    import pydantic

    from altiscope.schemas.aggregate import AGGREGATE_SCHEMA_VERSION, AggregateOutput

    assert AGGREGATE_SCHEMA_VERSION == 2
    payload = {
        "headline": "New billing pipeline",
        "claims": [
            {"kind": "feature", "text": "Added retries", "sources": ["PR-1", "PR-2"]},
        ],
        "narrative": "Billing pipeline now retries on failure.",
    }
    parsed = AggregateOutput.model_validate(payload)
    assert parsed.headline == "New billing pipeline"
    assert parsed.claims[0].sources == ["PR-1", "PR-2"]

    with pytest.raises(pydantic.ValidationError):
        AggregateOutput.model_validate({**payload, "extra_field": "disallowed"})
