"""Shared prompt and model-call persistence for PR and aggregate reports."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from altiscope.aggregate.generate import AggregateAttempt
from altiscope.llm.execution import StructuredAttempt
from altiscope.llm.provider import Usage
from altiscope.llm.registry import Registry
from altiscope.llm.router import RoutingDecision
from altiscope.llm.tokens import estimate_tokens
from altiscope.prompts import Prompt
from altiscope.store.hashing import hash_text
from altiscope.store.recipes import RecipeVersion
from altiscope.store.snapshots import insert
from altiscope.summarize.generate import Attempt

_OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class _Cost:
    usage_status: str
    cost_status: str
    cost_usd: float | None
    cache_read_rate: float | None
    cache_write_rate: float | None
    cache_rate_fallback: bool


def _attempt_status(attempt: Attempt | AggregateAttempt | StructuredAttempt) -> str:
    result = attempt.result
    if result.stop_reason == "refusal":
        return "refused"
    if result.stop_reason in ("transport_error", "max_tokens", "unknown"):
        return "failed"
    return "succeeded" if result.ok and not attempt.errors else "invalid_output"


def _request_hashes(request: Mapping[str, object], raw_text: str) -> tuple[str, str]:
    # Plain sort_keys (not canonical_json) is what existing call rows were hashed with.
    return hash_text(json.dumps(request, sort_keys=True)), hash_text(raw_text)


def _measure_cost(
    usage: Usage,
    *,
    input_rate: float,
    output_rate: float,
    cache_read_rate: float | None,
    cache_write_rate: float | None,
    endpoint: str | None,
    pricing_trusted: bool = True,
) -> _Cost:
    """Shared usage/cost accounting; callers differ only in where rates come from."""
    declared_cache_rates_missing = cache_read_rate is None or cache_write_rate is None
    if endpoint == _OPENROUTER_ENDPOINT:
        cache_read_rate = cache_read_rate or input_rate
        cache_write_rate = cache_write_rate or input_rate
    usage_status = (
        "measured"
        if any(
            (
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_read_tokens,
                usage.cache_write_tokens,
            )
        )
        else "unavailable"
    )
    cache_pricing_complete = (usage.cache_read_tokens == 0 or cache_read_rate is not None) and (
        usage.cache_write_tokens == 0 or cache_write_rate is not None
    )
    complete = usage_status == "measured" and pricing_trusted and cache_pricing_complete
    cost = None
    if complete:
        cost = (
            usage.input_tokens * input_rate
            + usage.output_tokens * output_rate
            + usage.cache_read_tokens * (cache_read_rate or 0)
            + usage.cache_write_tokens * (cache_write_rate or 0)
        ) / 1_000_000
    return _Cost(
        usage_status=usage_status,
        cost_status="complete" if complete else "unavailable",
        cost_usd=cost,
        cache_read_rate=cache_read_rate,
        cache_write_rate=cache_write_rate,
        cache_rate_fallback=endpoint == _OPENROUTER_ENDPOINT and declared_cache_rates_missing,
    )


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
    # Migration tests generate an M1 report before applying M3's accounting
    # columns. Keep that historical write path valid during an upgrade.
    has_accounting_columns = bool(
        conn.execute(
            "SELECT 1 FROM pg_attribute WHERE attrelid='llm_calls'::regclass "
            "AND attname='usage_status' AND NOT attisdropped"
        ).fetchone()
    )
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
        provider = registry.provider_for(model.id)
        measured = _measure_cost(
            result.usage,
            input_rate=model.input_usd_per_mtok,
            output_rate=model.output_usd_per_mtok,
            cache_read_rate=model.cache_read_usd_per_mtok,
            cache_write_rate=model.cache_write_usd_per_mtok,
            endpoint=provider.base_url,
        )
        request_hash, response_hash = _request_hashes(request, result.raw_text)
        values = dict(
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
            cost_usd=measured.cost_usd
            if has_accounting_columns
            else (
                result.usage.input_tokens * model.input_usd_per_mtok
                + result.usage.output_tokens * model.output_usd_per_mtok
            )
            / 1_000_000,
            latency_ms=result.latency_ms,
            provider_request_id=result.provider_request_id,
            stop_reason=result.stop_reason,
            status=_attempt_status(attempt),
            error="; ".join(attempt.errors) or None,
            request_hash=request_hash,
            response_hash=response_hash,
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
        )
        if has_accounting_columns:
            values.update(
                usage_status=measured.usage_status,
                cost_status=measured.cost_status,
                pricing_basis=Jsonb(
                    {
                        "provenance": "model_registry",
                        "model_registry_key": model.id,
                        "currency": "USD",
                        "input_usd_per_mtok": model.input_usd_per_mtok,
                        "output_usd_per_mtok": model.output_usd_per_mtok,
                        "cache_read_usd_per_mtok": measured.cache_read_rate,
                        "cache_write_usd_per_mtok": measured.cache_write_rate,
                        "cache_rate_fallback": measured.cache_rate_fallback,
                    }
                ),
                actual_output_mode=result.output_mode,
            )
        call_id = insert(conn, "llm_calls", values)
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
        measured = _measure_cost(
            result.usage,
            input_rate=config.pricing.input_usd_per_mtok,
            output_rate=config.pricing.output_usd_per_mtok,
            cache_read_rate=config.pricing.cache_read_usd_per_mtok,
            cache_write_rate=config.pricing.cache_write_usd_per_mtok,
            endpoint=config.provider.endpoint,
            pricing_trusted=config.pricing.status == "configured_estimate",
        )
        # Recorded pricing basis has always shown 0 (not null) for an unset cache rate
        # once the cost is complete.
        complete = measured.cost_status == "complete"
        cache_read_rate = (measured.cache_read_rate or 0) if complete else measured.cache_read_rate
        cache_write_rate = (
            (measured.cache_write_rate or 0) if complete else measured.cache_write_rate
        )
        request_hash, response_hash = _request_hashes(request, result.raw_text)
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
                usage_status=measured.usage_status,
                cost_usd=measured.cost_usd,
                cost_status=measured.cost_status,
                pricing_basis=Jsonb(
                    {
                        **config.pricing.model_dump(mode="json"),
                        "cache_read_usd_per_mtok": cache_read_rate,
                        "cache_write_usd_per_mtok": cache_write_rate,
                        "cache_rate_fallback": measured.cache_rate_fallback,
                    }
                ),
                latency_ms=result.latency_ms,
                provider_request_id=result.provider_request_id,
                stop_reason=result.stop_reason,
                actual_output_mode=result.output_mode,
                status=_attempt_status(attempt),
                error="; ".join(attempt.errors) or None,
                request_hash=request_hash,
                response_hash=response_hash,
                request_payload=Jsonb(request) if retention == "full" else None,
                response_text=result.raw_text if retention == "full" else None,
                selected_config=Jsonb(config.model_dump(mode="json")),
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
            ),
        )
        call_ids.append(call_id)
    return tuple(call_ids)
