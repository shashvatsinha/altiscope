from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.conftest import REPO_ROOT

from altiscope.llm.registry import Registry
from altiscope.llm.router import RoutingError, route


def _registry(**overrides: object) -> Registry:
    base: dict[str, object] = {
        "models": {
            "small": {
                "provider": "p",
                "display_name": "S",
                "context_window": 200_000,
                "max_output_tokens": 64_000,
                "input_usd_per_mtok": 1,
                "output_usd_per_mtok": 5,
            },
            "big": {
                "provider": "p",
                "display_name": "B",
                "context_window": 1_000_000,
                "max_output_tokens": 128_000,
                "input_usd_per_mtok": 5,
                "output_usd_per_mtok": 25,
            },
        },
        "input_budget_fraction": 0.75,
        "stages": {
            "pr_summary": {"candidates": ["small", "big"], "reserved_output_tokens": 16_000},
            "aggregate": {"candidates": ["big"], "reserved_output_tokens": 16_000},
            "verify": {
                "candidates": ["small", "big"],
                "reserved_output_tokens": 4_000,
                "must_differ_from_producer": True,
            },
        },
    }
    base.update(overrides)
    return Registry.model_validate(base)


def test_shipped_registry_loads_and_routes():
    reg = Registry.load(REPO_ROOT / "config" / "models.yaml")
    for stage in ("pr_summary", "aggregate", "verify"):
        d = route(reg, stage, 50_000)
        assert d.model_id in reg.models
        assert d.reason


def test_budget_math():
    reg = _registry()
    # 200k * 0.75 - 16k
    assert reg.input_budget("small", "pr_summary") == 134_000
    assert reg.input_budget("big", "aggregate") == 734_000


def test_default_route_records_reason():
    d = route(_registry(), "pr_summary", 10_000)
    assert d.model_id == "small"
    assert d.rule == "default"
    assert d.candidates == ("small", "big")
    assert d.effort == "high"


def test_escalates_when_input_exceeds_first_candidate():
    d = route(_registry(), "pr_summary", 300_000)
    assert d.model_id == "big"
    assert d.rule == "escalated_for_size"
    assert "small budget 134,000 < input 300,000" in d.reason


def test_verify_skips_producer():
    d = route(_registry(), "verify", 10_000, producer_model_id="small")
    assert d.model_id == "big"
    assert d.rule == "differs_from_producer"
    assert "small is the producer" in d.reason


def test_no_fit_raises_with_explanation():
    with pytest.raises(RoutingError, match="no candidate for aggregate fits 900,000"):
        route(_registry(), "aggregate", 900_000)


def test_negative_input_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        route(_registry(), "aggregate", -1)


def test_registry_rejects_unknown_candidate():
    with pytest.raises(ValidationError, match="unknown model 'nope'"):
        _registry(
            stages={
                "pr_summary": {"candidates": ["nope"], "reserved_output_tokens": 1},
                "aggregate": {"candidates": ["big"], "reserved_output_tokens": 1},
                "verify": {"candidates": ["big"], "reserved_output_tokens": 1},
            }
        )


def test_registry_rejects_missing_stage():
    with pytest.raises(ValidationError, match="missing stage 'verify'"):
        _registry(
            stages={
                "pr_summary": {"candidates": ["big"], "reserved_output_tokens": 1},
                "aggregate": {"candidates": ["big"], "reserved_output_tokens": 1},
            }
        )


def test_registry_rejects_reserving_more_output_than_model_allows():
    with pytest.raises(ValidationError, match="reserves 70000 output tokens"):
        _registry(
            stages={
                "pr_summary": {"candidates": ["small"], "reserved_output_tokens": 70_000},
                "aggregate": {"candidates": ["big"], "reserved_output_tokens": 1},
                "verify": {"candidates": ["big"], "reserved_output_tokens": 1},
            }
        )
