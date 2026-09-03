from __future__ import annotations

import pytest
from pydantic import ValidationError

from altiscope.llm.registry import Registry
from altiscope.llm.router import RoutingError, route
from tests.conftest import REPO_ROOT


def _registry(**overrides: object) -> Registry:
    base: dict[str, object] = {
        "providers": {
            "anthropic": {"kind": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"},
            "local": {"kind": "openai_compatible", "base_url": "http://localhost:11434/v1"},
        },
        "models": {
            "small": {
                "provider": "anthropic",
                "display_name": "S",
                "context_window": 200_000,
                "max_output_tokens": 64_000,
                "capabilities": ["json_schema", "token_counting"],
            },
            "big": {
                "provider": "anthropic",
                "display_name": "B",
                "context_window": 1_000_000,
                "max_output_tokens": 128_000,
            },
            "oss": {
                "provider": "local",
                "model_name": "llama3.3:70b",
                "display_name": "OSS",
                "context_window": 131_072,
                "max_output_tokens": 16_384,
                "capabilities": ["json_mode"],
            },
        },
        "input_budget_fraction": 0.75,
        "stages": {
            "pr_summary": {"candidates": ["small", "big"], "reserved_output_tokens": 16_000},
            "aggregate": {"candidates": ["big"], "reserved_output_tokens": 16_000},
            "verify": {
                "candidates": ["small", "big", "oss"],
                "reserved_output_tokens": 4_000,
                "producer_independence": "model",
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
    assert reg.models["llama-3.3-70b"].wire_name == "llama3.3:70b"
    assert reg.provider_for("llama-3.3-70b").kind == "openai_compatible"


@pytest.mark.parametrize("name", ["openai", "ollama", "mixed"])
def test_example_registries_load(name: str):
    reg = Registry.load(REPO_ROOT / "config" / "examples" / f"{name}.yaml")
    for stage in ("pr_summary", "aggregate", "verify"):
        assert route(reg, stage, 20_000).model_id in reg.models


def test_structured_output_mode_follows_capabilities():
    reg = _registry()
    assert reg.models["small"].structured_output_mode == "native"
    assert reg.models["oss"].structured_output_mode == "json_mode"
    assert reg.models["big"].structured_output_mode == "prompt"


def test_budget_math():
    reg = _registry()
    # 200k * 0.75 - 16k
    assert reg.input_budget("small", "pr_summary") == 134_000
    assert reg.input_budget("big", "aggregate") == 734_000


def test_default_route_records_reason():
    d = route(_registry(), "pr_summary", 10_000)
    assert d.model_id == "small"
    assert d.provider == "anthropic"
    assert d.rule == "default"
    assert d.candidates == ("small", "big")
    assert d.effort == "high"


def test_escalates_when_input_exceeds_first_candidate():
    d = route(_registry(), "pr_summary", 300_000)
    assert d.model_id == "big"
    assert d.rule == "escalated_for_size"
    assert "small budget 134,000 < input 300,000" in d.reason


def test_verify_skips_producer_model():
    d = route(_registry(), "verify", 10_000, producer_model_id="small")
    assert d.model_id == "big"
    assert d.rule == "independent_of_producer"
    assert "small is the producer" in d.reason


def test_verify_can_require_a_different_provider():
    reg = _registry()
    reg.stages["verify"].producer_independence = "provider"
    d = route(reg, "verify", 10_000, producer_model_id="small")
    assert d.model_id == "oss"
    assert d.provider == "local"
    assert "big shares provider 'anthropic' with the producer" in d.reason


def test_independence_is_ignored_when_stage_does_not_ask():
    d = route(_registry(), "pr_summary", 10_000, producer_model_id="small")
    assert d.model_id == "small" and d.rule == "default"


def test_no_fit_raises_with_explanation():
    with pytest.raises(RoutingError, match="no candidate for aggregate fits 900,000"):
        route(_registry(), "aggregate", 900_000)


def test_negative_input_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        route(_registry(), "aggregate", -1)


def test_registry_rejects_unknown_provider():
    with pytest.raises(ValidationError, match="unknown provider 'nope'"):
        _registry(
            models={
                "m": {
                    "provider": "nope",
                    "display_name": "M",
                    "context_window": 1,
                    "max_output_tokens": 1,
                },
            }
        )


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
