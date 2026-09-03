"""Routing: pick a model for a stage given the input size, and say why.

The decision is stored on every llm_calls row (design principle 6). Routing is by fit
and declared preference only; there is no cost-based logic here by design (ADR-0005).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from altiscope.llm.registry import Registry
from altiscope.llm.types import Effort, Stage


class RoutingError(Exception):
    """No candidate can take the input. The caller must reduce it (see aggregate.planner)."""


@dataclass(frozen=True)
class RoutingDecision:
    stage: Stage
    model_id: str
    provider: str
    effort: Effort
    rule: str
    reason: str
    estimated_input_tokens: int
    candidates: tuple[str, ...] = field(default_factory=tuple)


def route(
    registry: Registry,
    stage: Stage,
    estimated_input_tokens: int,
    *,
    producer_model_id: str | None = None,
) -> RoutingDecision:
    """Choose the first candidate, in declared order, that fits the input.

    `producer_model_id` is the model that produced the artifact being verified; when the
    stage declares `must_differ_from_producer`, that model is skipped.
    """
    if estimated_input_tokens < 0:
        msg = "estimated_input_tokens must be non-negative"
        raise ValueError(msg)
    cfg = registry.stages[stage]
    candidates = tuple(cfg.candidates)
    skipped: list[str] = []

    for index, model_id in enumerate(candidates):
        if cfg.must_differ_from_producer and model_id == producer_model_id:
            skipped.append(f"{model_id} is the producer")
            continue
        budget = registry.input_budget(model_id, stage)
        if estimated_input_tokens > budget:
            skipped.append(f"{model_id} budget {budget:,} < input {estimated_input_tokens:,}")
            continue

        spec = registry.models[model_id]
        if index == 0 and not skipped:
            rule, reason = "default", f"default candidate for {stage}"
        elif any(s.endswith("is the producer") for s in skipped) and all(
            s.endswith("is the producer") for s in skipped
        ):
            rule = "differs_from_producer"
            reason = f"{'; '.join(skipped)}; chose {model_id}"
        else:
            rule = "escalated_for_size"
            reason = f"{'; '.join(skipped)}; chose {model_id} (budget {budget:,})"
        return RoutingDecision(
            stage=stage,
            model_id=model_id,
            provider=spec.provider,
            effort=cfg.effort,
            rule=rule,
            reason=reason,
            estimated_input_tokens=estimated_input_tokens,
            candidates=candidates,
        )

    msg = f"no candidate for {stage} fits {estimated_input_tokens:,} tokens: {'; '.join(skipped)}"
    raise RoutingError(msg)
