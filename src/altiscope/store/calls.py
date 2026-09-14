"""Shared prompt and model-call persistence for PR and aggregate reports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from altiscope.aggregate.generate import AggregateAttempt
from altiscope.llm.execution import StructuredAttempt
from altiscope.llm.registry import Registry
from altiscope.llm.router import RoutingDecision
from altiscope.llm.tokens import estimate_tokens
from altiscope.prompts import Prompt
from altiscope.store.recipes import RecipeVersion
from altiscope.store.snapshots import insert
from altiscope.summarize.generate import Attempt


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def save_calls(
    conn: psycopg.Connection,
    *,
    attempts: tuple[Attempt, ...] | tuple[AggregateAttempt, ...],
    output_type: type[BaseModel],
    prompt: Prompt,
    decision: RoutingDecision,
    registry: Registry,
    retention: str,
    snapshot_id: int | None = None,
) -> tuple[int, tuple[int, ...]]:
    if retention not in ("full", "hashes_only"):
        raise ValueError("Unknown payload retention policy")
    model = registry.models[decision.model_id]
    prompt_row = conn.execute(
        "INSERT INTO prompt_versions(stage,name,content_hash,content,source_text) "
        "VALUES (%s,%s,%s,%s,%s) "
        "ON CONFLICT(stage,content_hash) DO UPDATE SET source_text="
        "COALESCE(prompt_versions.source_text,EXCLUDED.source_text) "
        "RETURNING id",
        (prompt.stage, prompt.version, prompt.content_hash, prompt.body, prompt.source_text),
    ).fetchone()
    assert prompt_row is not None
    prompt_id = int(prompt_row[0])
    call_id = 0
    generation_id = uuid4()
    call_ids: list[int] = []
    for ordinal, attempt in enumerate(attempts, 1):
        result = attempt.result
        request = dict(
            system=prompt.body,
            user=attempt.user,
            schema=output_type.model_json_schema(),
            model=model.wire_name,
            effort=decision.effort,
            output_mode=result.output_mode,
            max_tokens=registry.stages[decision.stage].reserved_output_tokens,
        )
        request_text = json.dumps(request, sort_keys=True)
        status = "succeeded" if result.ok and not attempt.errors else "invalid_output"
        if result.stop_reason == "refusal":
            status = "refused"
        elif result.stop_reason in ("transport_error", "max_tokens", "unknown"):
            status = "failed"
        call_id = insert(
            conn,
            "llm_calls",
            dict(
                stage=decision.stage,
                pull_request_id=snapshot_id,
                generation_id=generation_id,
                attempt_ordinal=ordinal,
                provider=decision.provider,
                model_id=result.model_id,
                prompt_version_id=prompt_id,
                schema_version=prompt.schema_version,
                effort=decision.effort,
                routing_rule=decision.rule,
                routing_reason=decision.reason,
                routing_candidates=list(decision.candidates),
                estimated_input_tokens=estimate_tokens(prompt.body)
                + estimate_tokens(attempt.user)
                + estimate_tokens(json.dumps(output_type.model_json_schema(), sort_keys=True))
                + 256,
                **asdict(result.usage),
                cost_usd=(
                    result.usage.input_tokens * model.input_usd_per_mtok
                    + result.usage.output_tokens * model.output_usd_per_mtok
                )
                / 1_000_000,
                latency_ms=result.latency_ms,
                provider_request_id=result.provider_request_id,
                stop_reason=result.stop_reason,
                status=status,
                error="; ".join(attempt.errors) or None,
                request_hash=_digest(request_text),
                response_hash=_digest(result.raw_text),
                request_payload=Jsonb(request) if retention == "full" else None,
                response_text=result.raw_text if retention == "full" else None,
                selected_config=Jsonb(
                    dict(
                        model=model.model_dump(mode="json"),
                        provider=registry.provider_for(model.id).model_dump(mode="json"),
                        stage=registry.stages[decision.stage].model_dump(mode="json"),
                        output_mode=result.output_mode,
                        input_budget_fraction=registry.input_budget_fraction,
                    )
                ),
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
            ),
        )
        call_ids.append(call_id)
    return prompt_id, tuple(call_ids)


def save_recipe_calls(
    conn: psycopg.Connection,
    *,
    attempts: tuple[Attempt, ...] | tuple[AggregateAttempt, ...] | tuple[StructuredAttempt, ...],
    recipe: RecipeVersion,
    retention: str,
    snapshot_id: int | None = None,
) -> tuple[int, ...]:
    """Persist actual attempts using only a recipe's frozen configuration."""
    if retention not in ("full", "hashes_only"):
        raise ValueError("Unknown payload retention policy")
    config = recipe.config
    generation_id = uuid4()
    call_ids: list[int] = []
    for ordinal, attempt in enumerate(attempts, 1):
        result = attempt.result
        request = dict(
            system=recipe.prompt.body,
            user=attempt.user,
            schema=recipe.output_type.model_json_schema(),
            model=config.model.wire_name,
            effort=config.generation.effective_effort,
            output_mode=config.model.output_mode,
            max_tokens=config.generation.reserved_output_tokens,
        )
        request_text = json.dumps(request, sort_keys=True)
        status = "succeeded" if result.ok and not attempt.errors else "invalid_output"
        if result.stop_reason == "refusal":
            status = "refused"
        elif result.stop_reason in ("transport_error", "max_tokens", "unknown"):
            status = "failed"
        usage_values = (
            result.usage.input_tokens,
            result.usage.output_tokens,
            result.usage.cache_read_tokens,
            result.usage.cache_write_tokens,
        )
        usage_status = "measured" if any(usage_values) else "unavailable"
        cost_status = (
            "complete"
            if usage_status == "measured" and config.pricing.status == "configured_estimate"
            else "unavailable"
        )
        cost = None
        if cost_status == "complete":
            cost = (
                (
                    result.usage.input_tokens
                    + result.usage.cache_read_tokens
                    + result.usage.cache_write_tokens
                )
                * config.pricing.input_usd_per_mtok
                + result.usage.output_tokens * config.pricing.output_usd_per_mtok
            ) / 1_000_000
        call_id = insert(
            conn,
            "llm_calls",
            dict(
                stage=config.stage,
                pull_request_id=snapshot_id,
                generation_id=generation_id,
                attempt_ordinal=ordinal,
                provider=config.provider.name,
                model_id=result.model_id,
                prompt_version_id=recipe.prompt_id,
                schema_version=config.output_contract.version,
                effort=config.generation.requested_effort,
                routing_rule="pinned_recipe",
                routing_reason=f"exact recipe version {recipe.id}",
                routing_candidates=[config.model.registry_key],
                estimated_input_tokens=estimate_tokens(recipe.prompt.body)
                + estimate_tokens(attempt.user)
                + estimate_tokens(
                    json.dumps(recipe.output_type.model_json_schema(), sort_keys=True)
                )
                + config.budget.schema_envelope_allowance,
                **asdict(result.usage),
                usage_status=usage_status,
                cost_usd=cost,
                cost_status=cost_status,
                pricing_basis=Jsonb(config.pricing.model_dump(mode="json")),
                latency_ms=result.latency_ms,
                provider_request_id=result.provider_request_id,
                stop_reason=result.stop_reason,
                actual_output_mode=result.output_mode,
                status=status,
                error="; ".join(attempt.errors) or None,
                request_hash=_digest(request_text),
                response_hash=_digest(result.raw_text),
                request_payload=Jsonb(request) if retention == "full" else None,
                response_text=result.raw_text if retention == "full" else None,
                selected_config=Jsonb(config.model_dump(mode="json")),
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
            ),
        )
        call_ids.append(call_id)
    return tuple(call_ids)
