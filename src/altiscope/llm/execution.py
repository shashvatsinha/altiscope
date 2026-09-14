"""Execute one exact structured request with bounded malformed-output repair."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel

from altiscope.llm.provider import GenerationResult, Provider
from altiscope.llm.registry import ModelSpec
from altiscope.llm.tokens import estimate_tokens
from altiscope.llm.types import Effort
from altiscope.llm.validation import sanitize_diagnostic


@dataclass(frozen=True)
class StructuredAttempt:
    user: str
    result: GenerationResult[BaseModel]
    errors: tuple[str, ...]
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True)
class StructuredExecution:
    output: BaseModel | None
    attempts: tuple[StructuredAttempt, ...]
    errors: tuple[str, ...]


def request_tokens(
    *,
    system: str,
    user: str,
    output_type: type[BaseModel],
    schema_envelope_allowance: int,
) -> int:
    schema = json.dumps(output_type.model_json_schema(), sort_keys=True)
    return (
        estimate_tokens(system)
        + estimate_tokens(user)
        + estimate_tokens(schema)
        + schema_envelope_allowance
    )


def execute_structured_request(
    provider: Provider,
    model: ModelSpec,
    *,
    system: str,
    user: str,
    output_type: type[BaseModel],
    max_tokens: int,
    effort: Effort,
    input_budget: int,
    schema_envelope_allowance: int,
    repair_limit: int,
) -> StructuredExecution:
    """Run one generation plus at most the configured single output replacement."""
    if max_tokens <= 0 or max_tokens > model.max_output_tokens:
        raise ValueError("invalid output token reservation")
    if repair_limit not in (0, 1):
        raise ValueError("comparison repair limit must be zero or one")
    effective_budget = min(input_budget, model.context_window - max_tokens)
    original_user = user
    current_user = user
    attempts: list[StructuredAttempt] = []
    errors: tuple[str, ...] = ()
    for _ in range(repair_limit + 1):
        if (
            request_tokens(
                system=system,
                user=current_user,
                output_type=output_type,
                schema_envelope_allowance=schema_envelope_allowance,
            )
            > effective_budget
        ):
            return StructuredExecution(
                None,
                tuple(attempts),
                ("oversized_input: complete request exceeds frozen recipe budget",),
            )
        started_at = datetime.now(UTC)
        result = provider.generate_structured(
            model=model,
            system=system,
            user=current_user,
            output_type=output_type,
            max_tokens=max_tokens,
            effort=effort,
        )
        output = result.parsed if result.ok else None
        errors = () if output is not None else (result.stop_reason,)
        if output is None and result.stop_reason in ("end_turn", "invalid_output"):
            errors = (*errors, sanitize_diagnostic(result.validation_error, output_type))
        attempts.append(
            StructuredAttempt(current_user, result, errors, started_at, datetime.now(UTC))
        )
        if output is not None:
            return StructuredExecution(output, tuple(attempts), ())
        if result.stop_reason not in ("end_turn", "invalid_output"):
            break
        current_user = (
            original_user + "\n\nReplace the malformed output once. Errors:\n" + "\n".join(errors)
        )
    return StructuredExecution(None, tuple(attempts), errors)
