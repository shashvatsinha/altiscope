"""Execute frozen recipes without production routing, caching, or publication."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

import psycopg

from altiscope.llm.credentials import api_key
from altiscope.llm.execution import classify_structured_failure, execute_structured_request
from altiscope.llm.provider import Provider
from altiscope.llm.providers import build_provider
from altiscope.store.baselines import is_primary_baseline, load_primary_baseline
from altiscope.store.comparisons import (
    ComparisonInvocation,
    ConditionLabel,
    StoredResult,
    TerminalResult,
    complete_invocation,
    create_invocation,
    find_comparison_result,
    load_source,
    reuse_result,
    save_result,
)
from altiscope.store.recipes import RecipeVersion, load_recipe

ProviderFactory = Callable[[RecipeVersion], Provider]
CostStatus = Literal["not_incurred", "complete", "partial", "unavailable"]


@dataclass(frozen=True)
class PlannedRecipe:
    recipe: RecipeVersion
    condition_label: ConditionLabel
    baseline_for_recipe_version_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class MemberMeasurements:
    call_count: int
    estimated_cost_usd: Decimal | None
    cost_status: CostStatus
    model_latency_ms: int | None


@dataclass(frozen=True)
class MemberOutcome:
    member_id: UUID
    recipe: RecipeVersion
    condition_label: ConditionLabel
    baseline_for_recipe_version_ids: tuple[UUID, ...]
    disposition: Literal["generated", "reused"]
    result: StoredResult
    current: MemberMeasurements
    origin: MemberMeasurements


@dataclass(frozen=True)
class ComparisonRun:
    invocation: ComparisonInvocation
    members: tuple[MemberOutcome, ...]
    elapsed_ms: int
    new_call_count: int
    new_estimated_cost_usd: Decimal | None
    new_cost_status: CostStatus


def _model_condition(recipe: RecipeVersion) -> tuple[str, str, str]:
    model = recipe.config.model
    identity = model.underlying_model_id or model.wire_name
    return recipe.config.provider.endpoint, recipe.config.provider.kind, identity


def plan_recipes(
    conn: psycopg.Connection,
    recipe_version_ids: tuple[UUID, ...],
    *,
    include_primary_baselines: bool,
) -> tuple[PlannedRecipe, ...]:
    """Expand assigned baselines once, preserving explicit recipe order and labels."""
    if len(recipe_version_ids) < 2 or len(set(recipe_version_ids)) != len(recipe_version_ids):
        raise ValueError("a comparison requires at least two distinct explicit recipe versions")
    explicit = [load_recipe(conn, recipe_id) for recipe_id in recipe_version_ids]
    ordered = list(explicit)
    baseline_targets: dict[UUID, list[UUID]] = {}
    if include_primary_baselines:
        for recipe in explicit:
            if is_primary_baseline(conn, recipe.id):
                continue
            assignment = load_primary_baseline(conn, recipe.id)
            if assignment is None:
                raise ValueError(
                    f"recipe {recipe.id} has no primary baseline; register one or use "
                    "--no-baselines explicitly"
                )
            baseline = assignment.recipe
            baseline_targets.setdefault(baseline.id, []).append(recipe.id)
            if all(existing.id != baseline.id for existing in ordered):
                ordered.append(baseline)

    reference = next((item for item in explicit if not is_primary_baseline(conn, item.id)), None)
    planned: list[PlannedRecipe] = []
    for recipe in ordered:
        if is_primary_baseline(conn, recipe.id):
            label: ConditionLabel = "primary_baseline"
        elif reference is not None and _model_condition(recipe) != _model_condition(reference):
            label = "model_comparison"
        else:
            label = "candidate"
        planned.append(PlannedRecipe(recipe, label, tuple(baseline_targets.get(recipe.id, ()))))
    return tuple(planned)


def _default_provider(recipe: RecipeVersion) -> Provider:
    registry = recipe.config.to_registry()
    spec = registry.provider_for(recipe.config.model.registry_key)
    return build_provider(spec, transport_retry_limit=recipe.config.provider.transport_retry_limit)


def _measure_result(conn: psycopg.Connection, result_id: UUID) -> MemberMeasurements:
    row = conn.execute(
        "SELECT count(c.id),sum(c.cost_usd),"
        "COALESCE(bool_and(c.cost_status='complete'),false),sum(c.latency_ms) "
        "FROM comparison_result_calls r JOIN llm_calls c ON c.id=r.call_id "
        "WHERE r.result_id=%s",
        (result_id,),
    ).fetchone()
    assert row is not None
    count = int(row[0])
    if count == 0:
        return MemberMeasurements(0, None, "not_incurred", None)
    complete = bool(row[2])
    return MemberMeasurements(
        count,
        Decimal(row[1]) if complete and row[1] is not None else None,
        "complete" if complete else "unavailable",
        int(row[3]) if row[3] is not None else None,
    )


def _current_measurements(
    conn: psycopg.Connection, member_id: UUID, *, origin: MemberMeasurements
) -> MemberMeasurements:
    row = conn.execute(
        "SELECT disposition,current_call_count,current_cost_usd,current_cost_status "
        "FROM comparison_members WHERE id=%s",
        (member_id,),
    ).fetchone()
    if row is None:
        raise ValueError("comparison member not found")
    if row[0] == "reused":
        return MemberMeasurements(0, None, "not_incurred", None)
    return MemberMeasurements(
        int(row[1]),
        Decimal(row[2]) if row[2] is not None else None,
        row[3],
        origin.model_latency_ms,
    )


def _totals(members: list[MemberOutcome]) -> tuple[int, Decimal | None, CostStatus]:
    call_count = sum(member.current.call_count for member in members)
    incurred = [member.current for member in members if member.current.call_count]
    if not incurred:
        return 0, None, "not_incurred"
    if any(item.cost_status != "complete" for item in incurred):
        return call_count, None, "unavailable"
    return (
        call_count,
        sum((item.estimated_cost_usd or Decimal(0) for item in incurred), Decimal(0)),
        "complete",
    )


def run_comparison(
    conn: psycopg.Connection,
    *,
    source_id: UUID,
    recipe_version_ids: tuple[UUID, ...],
    retention: Literal["full", "hashes_only"],
    execution_build: str,
    regenerate: bool = False,
    include_primary_baselines: bool = True,
    provider_factory: ProviderFactory | None = None,
) -> ComparisonRun:
    """Run or reuse every frozen member while retaining partial successes."""
    started = time.monotonic()
    source = load_source(conn, source_id)
    planned = plan_recipes(
        conn, recipe_version_ids, include_primary_baselines=include_primary_baselines
    )
    if any(item.recipe.stage != source.stage for item in planned):
        raise ValueError("all recipes must match the frozen source stage")
    invocation = create_invocation(
        conn,
        source_id=source.id,
        recipe_version_ids=tuple(item.recipe.id for item in planned),
        force_rerun=regenerate,
        retention=retention,
        execution_build=execution_build,
        condition_labels={item.recipe.id: item.condition_label for item in planned},
        baseline_targets={
            item.recipe.id: item.baseline_for_recipe_version_ids
            for item in planned
            if item.baseline_for_recipe_version_ids
        },
    )
    outcomes: list[MemberOutcome] = []
    factory = provider_factory or _default_provider
    for member, plan in zip(invocation.members, planned, strict=True):
        cached = None
        if not regenerate:
            cached = find_comparison_result(
                conn, source_id=source.id, recipe_version_id=plan.recipe.id
            )
        if cached is not None:
            result = reuse_result(conn, member_id=member.id, result_id=cached.id)
            disposition: Literal["generated", "reused"] = "reused"
        else:
            member_started = datetime.now(UTC)
            credential_reference = plan.recipe.config.provider.credential_reference
            if (
                provider_factory is None
                and credential_reference is not None
                and api_key(credential_reference) is None
            ):
                result = save_result(
                    conn,
                    member_id=member.id,
                    terminal=TerminalResult(
                        "preflight_failed",
                        member_started,
                        datetime.now(UTC),
                        error_code="credentials",
                        error_message="configured provider credential is unavailable",
                    ),
                    attempts=(),
                )
            else:
                try:
                    provider = factory(plan.recipe)
                except (ValueError, OSError):
                    result = save_result(
                        conn,
                        member_id=member.id,
                        terminal=TerminalResult(
                            "preflight_failed",
                            member_started,
                            datetime.now(UTC),
                            error_code="compatibility",
                            error_message="frozen provider configuration is not executable",
                        ),
                        attempts=(),
                    )
                else:
                    config = plan.recipe.config
                    model = config.to_registry().models[config.model.registry_key]
                    execution = execute_structured_request(
                        provider,
                        model,
                        system=plan.recipe.prompt.body,
                        user=source.prepared_text,
                        output_type=plan.recipe.output_type,
                        max_tokens=config.generation.reserved_output_tokens,
                        effort=config.generation.requested_effort,
                        input_budget=config.budget.input_limit,
                        schema_envelope_allowance=config.budget.schema_envelope_allowance,
                        repair_limit=config.budget.repair_limit,
                    )
                    if execution.output is not None:
                        terminal = TerminalResult(
                            "succeeded",
                            member_started,
                            datetime.now(UTC),
                            output=execution.output,
                        )
                    else:
                        status, error_code, message = classify_structured_failure(execution)
                        terminal = TerminalResult(
                            status,  # type: ignore[arg-type]
                            member_started,
                            datetime.now(UTC),
                            error_code=error_code,
                            error_message=message,
                        )
                    result = save_result(
                        conn, member_id=member.id, terminal=terminal, attempts=execution.attempts
                    )
            disposition = "generated"
        origin = _measure_result(conn, result.id)
        current = _current_measurements(conn, member.id, origin=origin)
        outcomes.append(
            MemberOutcome(
                member.id,
                plan.recipe,
                plan.condition_label,
                plan.baseline_for_recipe_version_ids,
                disposition,
                result,
                current,
                origin,
            )
        )
    complete_invocation(conn, invocation.id)
    call_count, cost, cost_status = _totals(outcomes)
    return ComparisonRun(
        invocation,
        tuple(outcomes),
        int((time.monotonic() - started) * 1000),
        call_count,
        cost,
        cost_status,
    )
