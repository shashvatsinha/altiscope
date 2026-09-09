"""Generate one aggregate node with bounded repair and complete-request budgeting.

Tree execution, routing, cache lookup and persistence belong to the M2 service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from altiscope.aggregate.inputs import ReportInput, render_inputs, underlying_pr_urls
from altiscope.aggregate.planner import estimate_aggregate_request_tokens
from altiscope.llm.provider import GenerationResult, Provider
from altiscope.llm.registry import ModelSpec
from altiscope.llm.types import Effort
from altiscope.schemas.aggregate import AggregateOutput


@dataclass(frozen=True)
class AggregateAttempt:
    user: str
    result: GenerationResult[AggregateOutput]
    errors: tuple[str, ...]
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True)
class GeneratedAggregate:
    output: AggregateOutput | None
    attempts: tuple[AggregateAttempt, ...]
    errors: tuple[str, ...]
    inputs: tuple[ReportInput, ...]

    @property
    def pr_urls(self) -> tuple[str, ...]:
        return underlying_pr_urls(self.inputs)


def generate_aggregate(
    provider: Provider,
    model: ModelSpec,
    *,
    system: str,
    user: str,
    inputs: tuple[ReportInput, ...],
    max_tokens: int,
    effort: Effort,
    input_budget: int,
) -> GeneratedAggregate:
    if max_tokens <= 0 or max_tokens > model.max_output_tokens:
        raise ValueError("Invalid output token reservation")
    input_budget = min(input_budget, model.context_window - max_tokens)
    attempts: list[AggregateAttempt] = []
    user = render_inputs(user, inputs)
    original_user = user
    errors: tuple[str, ...] = ()
    for _ in range(2):
        if estimate_aggregate_request_tokens(system, user) > input_budget:
            return GeneratedAggregate(
                None, tuple(attempts), ("oversized_input: complete request exceeds budget",), inputs
            )
        started_at = datetime.now(UTC)
        result = provider.generate_structured(
            model=model,
            system=system,
            user=user,
            output_type=AggregateOutput,
            max_tokens=max_tokens,
            effort=effort,
        )
        output = None
        errors = (result.stop_reason,)
        if result.ok and result.parsed is not None:
            output = result.parsed
            errors = ()
        attempts.append(AggregateAttempt(user, result, errors, started_at, datetime.now(UTC)))
        if output is not None:
            return GeneratedAggregate(output, tuple(attempts), (), inputs)
        if result.stop_reason not in ("end_turn", "invalid_output"):
            break
        user = (
            original_user + "\n\nReplace the malformed output once. Errors:\n" + "\n".join(errors)
        )
    return GeneratedAggregate(None, tuple(attempts), errors, inputs)
