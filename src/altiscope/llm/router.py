"""Select a model by estimated input size and configured preference, and return a reason.

Routing does not optimize cost. Saving the decision in llm_calls remains unbuilt.
See ADR-0005.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from altiscope.llm.registry import Registry
from altiscope.llm.types import Effort, Stage


class RoutingError(Exception):
    """No candidate meets the size and producer-exclusion rules."""


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


def _independence_block(
    registry: Registry, stage: Stage, candidate: str, producer_model_id: str | None
) -> str | None:
    """Return the configured producer-exclusion reason, or None if allowed."""
    mode = registry.stages[stage].producer_independence
    if mode == "none" or producer_model_id is None:
        return None
    if candidate == producer_model_id:
        return f"{candidate} is the producer"
    if mode == "provider":
        producer = registry.models.get(producer_model_id)
        if producer is not None and registry.models[candidate].provider == producer.provider:
            return f"{candidate} shares provider '{producer.provider}' with the producer"
    return None


def route(
    registry: Registry,
    stage: Stage,
    estimated_input_tokens: int,
    *,
    producer_model_id: str | None = None,
) -> RoutingDecision:
    """Choose the first candidate, in declared order, that fits the input and satisfies
    the stage's producer-independence rule.

    `producer_model_id` is the model that produced the artifact being verified.
    """
    if estimated_input_tokens < 0:
        msg = "estimated_input_tokens must be non-negative"
        raise ValueError(msg)
    cfg = registry.stages[stage]
    candidates = tuple(cfg.candidates)
    skipped_size: list[str] = []
    skipped_independence: list[str] = []

    for model_id in candidates:
        block = _independence_block(registry, stage, model_id, producer_model_id)
        if block is not None:
            skipped_independence.append(block)
            continue
        budget = registry.input_budget(model_id, stage)
        if estimated_input_tokens > budget:
            skipped_size.append(f"{model_id} budget {budget:,} < input {estimated_input_tokens:,}")
            continue

        spec = registry.models[model_id]
        if not skipped_size and not skipped_independence:
            rule, reason = "default", f"default candidate for {stage}"
        elif skipped_size:
            rule = "escalated_for_size"
            skipped = skipped_independence + skipped_size
            reason = f"{'; '.join(skipped)}; chose {model_id} (budget {budget:,})"
        else:
            rule = "independent_of_producer"
            reason = f"{'; '.join(skipped_independence)}; chose {model_id}"
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

    skipped = skipped_independence + skipped_size
    msg = f"no candidate for {stage} fits {estimated_input_tokens:,} tokens: {'; '.join(skipped)}"
    raise RoutingError(msg)
