"""Provider-neutral generation with one output repair and full-request budgeting."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from altiscope.llm.provider import GenerationResult, Provider
from altiscope.llm.registry import ModelSpec
from altiscope.llm.tokens import estimate_tokens
from altiscope.llm.types import Effort
from altiscope.schemas.pr_summary import PrReviewOutput
from altiscope.summarize.context import PrContext, render_user_prompt
from altiscope.summarize.publication import Publication, PublicationState, assess


@dataclass(frozen=True)
class Attempt:
    user: str
    result: GenerationResult[PrReviewOutput]
    errors: tuple[str, ...]
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True)
class GeneratedAccount:
    publication: Publication
    attempts: tuple[Attempt, ...]


def request_tokens(system: str, user: str) -> int:
    schema = json.dumps(PrReviewOutput.model_json_schema(), sort_keys=True)
    # Schema plus instruction/envelope allowance; estimates are not exact token counts.
    return estimate_tokens(system) + estimate_tokens(user) + estimate_tokens(schema) + 256


def generate_account(
    ctx: PrContext,
    provider: Provider,
    model: ModelSpec,
    *,
    system: str,
    max_tokens: int,
    effort: Effort,
    input_budget: int,
) -> GeneratedAccount:
    user = render_user_prompt(ctx)
    attempts: list[Attempt] = []
    publication = assess(None, ctx)
    for _ in range(2):
        if request_tokens(system, user) > input_budget:
            return GeneratedAccount(
                Publication(
                    PublicationState.needs_review,
                    None,
                    ("oversized_input: complete request exceeds budget",),
                ),
                tuple(attempts),
            )
        started_at = datetime.now(UTC)
        result = provider.generate_structured(
            model=model,
            system=system,
            user=user,
            output_type=PrReviewOutput,
            max_tokens=max_tokens,
            effort=effort,
        )
        publication = assess(result.parsed if result.ok else None, ctx)
        errors = publication.errors if result.ok else (result.stop_reason,)
        if not result.ok:
            publication = Publication(PublicationState.needs_review, None, errors)
        attempts.append(Attempt(user, result, errors, started_at, datetime.now(UTC)))
        if publication.state == PublicationState.published:
            return GeneratedAccount(publication, tuple(attempts))
        if result.stop_reason not in ("end_turn", "invalid_output"):
            return GeneratedAccount(publication, tuple(attempts))
        user = render_user_prompt(ctx) + "\n\nRepair the output once. Errors:\n" + "\n".join(errors)
    return GeneratedAccount(publication, tuple(attempts))
