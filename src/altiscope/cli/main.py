"""The `altiscope` command."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, cast
from uuid import UUID

import typer

from altiscope.config import load_settings
from altiscope.llm.registry import Registry
from altiscope.llm.router import RoutingError, route
from altiscope.llm.types import STAGES, Stage
from altiscope.prompts import list_prompts
from altiscope.store.evaluation import EffortComponent, EffortMeasure

if TYPE_CHECKING:
    import psycopg

app = typer.Typer(
    help="Altitude-appropriate visibility into engineering work.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
db_app = typer.Typer(help="Database migrations.", no_args_is_help=True)
models_app = typer.Typer(help="Model registry and routing.", no_args_is_help=True)
prompts_app = typer.Typer(help="Versioned prompts.", no_args_is_help=True)
recipes_app = typer.Typer(help="Immutable generation recipes.", no_args_is_help=True)
comparisons_app = typer.Typer(help="Reproducible frozen-source comparisons.", no_args_is_help=True)
reviews_app = typer.Typer(help="Guided exact-result human reviews.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(models_app, name="models")
app.add_typer(prompts_app, name="prompts")
app.add_typer(recipes_app, name="recipes")
app.add_typer(comparisons_app, name="comparisons")
app.add_typer(reviews_app, name="reviews")


def _prompt_choice(prompt: str, choices: tuple[str, ...], *, default: str) -> str:
    value = typer.prompt(prompt, default=default).strip()
    if value not in choices:
        raise typer.BadParameter(f"{prompt} must be one of {', '.join(choices)}")
    return value


def _prompt_effort(component: EffortComponent) -> EffortMeasure:
    status = _prompt_choice(
        f"{component} effort status",
        ("measured", "not_applicable", "unavailable"),
        default="measured",
    )
    if status == "measured":
        value = typer.prompt(f"{component} active milliseconds (zero is retained)", type=int)
        method = _prompt_choice(
            f"{component} measurement method", ("timer", "estimated"), default="timer"
        )
        return EffortMeasure(
            component=component,
            status="measured",
            value=value,
            method=cast(Literal["timer", "estimated"], method),
        )
    if status == "unavailable":
        reason = typer.prompt(f"Why {component} effort is unavailable")
        return EffortMeasure(component=component, status="unavailable", unavailable_reason=reason)
    return EffortMeasure(component=component, status="not_applicable")


def _prompt_usefulness(prefix: str) -> tuple[str, int | None, str | None]:
    status = _prompt_choice(
        f"{prefix} usefulness status",
        ("measured", "unavailable", "not_applicable"),
        default="measured",
    )
    if status != "measured":
        return status, None, None
    score = typer.prompt(f"{prefix} usefulness score (1-5)", type=int)
    if not 1 <= score <= 5:
        raise typer.BadParameter("usefulness score must be from 1 to 5")
    rationale = typer.prompt(f"{prefix} usefulness rationale")
    return status, score, rationale


def _capture_initial_revision(conn: psycopg.Connection, session_id: UUID) -> UUID:
    """Reload a durable session and commit its one immutable initial revision."""
    from altiscope.review import render_frozen_source, render_review_result
    from altiscope.store.comparisons import load_result, load_source
    from altiscope.store.evaluation import (
        ReviewRevisionInput,
        append_review_revision,
        get_preparation,
        load_review_record,
        save_preparation,
    )

    record = load_review_record(conn, session_id)
    revisions = cast(list[dict[str, object]], record["revisions"])
    if revisions:
        raise ValueError("review session already has an initial revision")
    result = load_result(conn, UUID(str(record["result_id"])))
    source = load_source(conn, result.source_id)
    reviewer = str(record["reviewer_id"])
    case = cast(dict[str, object], record["case"])
    case_id = str(case["id"])
    typer.echo(render_frozen_source(source), nl=False)
    preparation = get_preparation(conn, source_id=source.id, reviewer_id=reviewer, case_id=case_id)
    if preparation is None:
        preparation_effort = _prompt_effort("preparation")
        save_preparation(
            conn,
            source_id=source.id,
            reviewer_id=reviewer,
            case_id=case_id,
            effort=preparation_effort,
        )
    else:
        typer.echo(f"Reusing preparation {preparation[0]}: {preparation[1].model_dump_json()}")

    typer.echo(render_review_result(result), nl=False)
    reading_effort = _prompt_effort("reading")
    typer.echo("Check the complete result against the frozen source shown above.")
    checking_effort = _prompt_effort("checking")
    correctness = _prompt_choice(
        "Whole-result correctness", ("correct", "incorrect", "unclear"), default="correct"
    )
    correctness_rationale = typer.prompt(
        "Correctness rationale (optional)", default="", show_default=False
    ).strip()
    correction = typer.prompt(
        "Corrected account text (leave blank when no correction is performed)",
        default="",
        show_default=False,
    ).strip()
    correction_effort = (
        _prompt_effort("correction")
        if correction
        else EffortMeasure(component="correction", status="not_applicable")
    )
    usefulness_status, usefulness_score, usefulness_rationale = _prompt_usefulness("Pre-assessment")
    prior_exposure = str(record["declared_prior_assessment_exposure"])
    exposures = cast(list[dict[str, object]], record["exposures"])
    blind_status = (
        "confirmed_unexposed"
        if prior_exposure == "none_declared" and not exposures
        else "unknown"
        if prior_exposure == "unknown"
        else "known_exposed"
    )
    revision_id = append_review_revision(
        conn,
        review_session_id=session_id,
        revision=ReviewRevisionInput(
            kind="initial_blind",
            blind_status=blind_status,
            correctness_label=cast(Literal["correct", "incorrect", "unclear"], correctness),
            correctness_rationale=correctness_rationale or None,
            correction=correction or None,
            usefulness_status=cast(
                Literal["measured", "unavailable", "not_applicable"], usefulness_status
            ),
            usefulness_score=usefulness_score,
            usefulness_rationale=usefulness_rationale,
            effort=(reading_effort, checking_effort, correction_effort),
            created_at=datetime.now(UTC),
        ),
        exposure_ids_seen=tuple(UUID(str(item["exposure_id"])) for item in exposures),
    )
    typer.echo("Initial judgment committed; it will not be overwritten.")
    return revision_id


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply pending SQL migrations."""
    from altiscope.store.db import connect
    from altiscope.store.migrate import apply_pending

    settings = load_settings()
    with connect(settings.database_url) as conn:
        applied = apply_pending(conn, settings.migrations_dir)
    if applied:
        for version in applied:
            typer.echo(f"applied {version}")
    else:
        typer.echo("nothing to apply")


@models_app.command("list")
def models_list() -> None:
    """Show models and per-stage routing from the registry."""
    settings = load_settings()
    registry = Registry.load(settings.models_config)
    typer.echo("providers:")
    for prov in registry.providers.values():
        auth = f"key from ${prov.api_key_env}" if prov.api_key_env else "no auth"
        typer.echo(f"  {prov.name:<12} {prov.kind:<18} {prov.base_url or '(sdk default)'}  {auth}")
    typer.echo("models:")
    for spec in registry.models.values():
        cache_rates = (
            f" cache=${spec.cache_read_usd_per_mtok}/${spec.cache_write_usd_per_mtok}"
            if spec.cache_read_usd_per_mtok is not None
            and spec.cache_write_usd_per_mtok is not None
            else " cache=unconfigured"
        )
        typer.echo(
            f"  {spec.id:<20} {spec.provider:<10} ctx={spec.context_window:>9,} "
            f"out={spec.max_output_tokens:>7,} "
            f"input/output=${spec.input_usd_per_mtok}/${spec.output_usd_per_mtok}"
            f"{cache_rates} per MTok  "
            f"[{spec.provider}] {sorted(spec.capabilities)}"
        )
    typer.echo("stages:")
    for stage, cfg in registry.stages.items():
        extra = (
            f" (independent of producer: {cfg.producer_independence})"
            if cfg.producer_independence != "none"
            else ""
        )
        typer.echo(
            f"  {stage:<12} effort={cfg.effort:<6} reserved_out={cfg.reserved_output_tokens:>6,} "
            f"candidates={cfg.candidates}{extra}"
        )


@models_app.command("route")
def models_route(
    stage: Annotated[str, typer.Argument(help=f"one of {', '.join(STAGES)}")],
    input_tokens: Annotated[int, typer.Option(help="estimated input size")] = 50_000,
    producer: Annotated[str | None, typer.Option(help="producer model, for verify")] = None,
) -> None:
    """Show which model a stage would use for an input of a given size, and why."""
    if stage not in STAGES:
        raise typer.BadParameter(f"stage must be one of {STAGES}")
    settings = load_settings()
    registry = Registry.load(settings.models_config)
    typed_stage: Stage = stage  # type: ignore[assignment]
    try:
        decision = route(registry, typed_stage, input_tokens, producer_model_id=producer)
    except RoutingError as exc:
        typer.echo(f"no route: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"model:  {decision.model_id} ({decision.provider}, effort={decision.effort})")
    typer.echo(f"rule:   {decision.rule}")
    typer.echo(f"reason: {decision.reason}")


@prompts_app.command("list")
def prompts_list() -> None:
    """Show prompt versions and their content hashes."""
    settings = load_settings()
    for p in list_prompts(settings.prompts_dir):
        typer.echo(
            f"{p.stage:<12} {p.version:<4} schema={p.schema_version} "
            f"{p.content_hash[:16]}  {p.path}"
        )


@recipes_app.command("save")
def recipes_save(  # noqa: PLR0917
    name: Annotated[str, typer.Argument(help="stable recipe name")],
    model: Annotated[str, typer.Option(help="model registry key")],
    stage: Annotated[str, typer.Option(help="pr_summary, aggregate, or verify")],
    prompt_version: Annotated[
        str | None, typer.Option(help="exact prompt version; default is current")
    ] = None,
    effort: Annotated[str | None, typer.Option(help="low, medium, high, xhigh, or max")] = None,
    reserved_output_tokens: Annotated[
        int | None, typer.Option(help="override reserved output tokens")
    ] = None,
) -> None:
    """Resolve the registry and prompt into a new immutable recipe version."""
    from altiscope.llm.types import Effort
    from altiscope.store.db import connect
    from altiscope.store.recipes import RecipeOverrides, create_recipe

    if stage not in ("pr_summary", "aggregate", "verify"):
        raise typer.BadParameter("stage must be pr_summary, aggregate, or verify")
    if effort not in (None, "low", "medium", "high", "xhigh", "max"):
        raise typer.BadParameter("effort must be low, medium, high, xhigh, or max")
    typed_stage: Stage = stage  # type: ignore[assignment]
    typed_effort: Effort | None = effort  # type: ignore[assignment]
    settings = load_settings()
    prompts = [p for p in list_prompts(settings.prompts_dir) if p.stage == typed_stage]
    if prompt_version is not None:
        prompts = [p for p in prompts if p.version == prompt_version]
    if not prompts:
        raise typer.BadParameter("matching prompt version not found")
    prompt = max(prompts, key=lambda item: int(item.version.lstrip("v")))
    try:
        with connect(settings.database_url) as conn:
            recipe = create_recipe(
                conn,
                name=name,
                registry_key=model,
                prompt=prompt,
                registry=Registry.load(settings.models_config),
                overrides=RecipeOverrides(
                    effort=typed_effort, reserved_output_tokens=reserved_output_tokens
                ),
            )
    except (ValueError, OSError) as exc:
        typer.echo(f"Could not save recipe: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(
        f"Saved {recipe.name} v{recipe.version} ({recipe.id}); {recipe.stage}, "
        f"{recipe.config.model.registry_key}, prompt {recipe.prompt.version}, "
        f"schema {recipe.config.output_contract.version}"
    )


@recipes_app.command("list")
def recipes_list() -> None:
    """List every immutable recipe version."""
    from altiscope.store.db import connect
    from altiscope.store.recipes import list_recipes

    with connect(load_settings().database_url) as conn:
        rows = list_recipes(conn)
    for recipe_id, name, version, stage, digest in rows:
        typer.echo(f"{name} v{version}  {stage:<10} {digest[:16]}  {recipe_id}")


@recipes_app.command("show")
def recipes_show(
    name: Annotated[str, typer.Argument(help="recipe name")],
    version: Annotated[int | None, typer.Option(help="exact version; default is latest")] = None,
) -> None:
    """Inspect the exact frozen configuration and retained prompt content."""
    import json

    from altiscope.store.db import connect
    from altiscope.store.recipes import load_recipe_version

    try:
        with connect(load_settings().database_url) as conn:
            recipe = load_recipe_version(conn, name, version)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"{recipe.name} v{recipe.version} ({recipe.id})")
    typer.echo(json.dumps(recipe.config.model_dump(mode="json"), indent=2, sort_keys=True))
    typer.echo("Retained prompt source:")
    typer.echo(recipe.prompt.source_text, nl=False)


@recipes_app.command("baseline")
def recipes_baseline(
    recipe_id: Annotated[str, typer.Argument(help="exact candidate recipe-version UUID")],
    rationale: Annotated[
        str | None, typer.Option(help="why this prompt is the primary baseline")
    ] = None,
) -> None:
    """Assign the shipped minimal prompt as an exact recipe's primary baseline."""
    from uuid import UUID

    import psycopg

    from altiscope.prompts import load_prompt
    from altiscope.store.baselines import DEFAULT_BASELINE_RATIONALE, register_primary_baseline
    from altiscope.store.db import connect
    from altiscope.store.recipes import load_recipe

    settings = load_settings()
    try:
        parsed_id = UUID(recipe_id)
        with connect(settings.database_url) as conn:
            candidate = load_recipe(conn, parsed_id)
            prompt = load_prompt(settings.prompts_dir / "baseline" / f"{candidate.stage}-v1.md")
            baseline = register_primary_baseline(
                conn,
                recipe_version_id=parsed_id,
                prompt=prompt,
                rationale=rationale or DEFAULT_BASELINE_RATIONALE,
            )
    except (ValueError, OSError, psycopg.Error) as exc:
        typer.echo(f"Could not register baseline: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(
        f"Primary baseline {baseline.recipe.name} v{baseline.recipe.version} "
        f"({baseline.recipe.id}) for {recipe_id}; prompt {baseline.recipe.prompt.version}"
    )


@comparisons_app.command("run")
def comparisons_run(
    source_id: Annotated[str, typer.Argument(help="exact frozen comparison-source UUID")],
    recipes: Annotated[
        list[str], typer.Option("--recipe", help="exact recipe-version UUID; repeat at least twice")
    ],
    regenerate: Annotated[
        bool, typer.Option(help="bypass successful comparison results and preserve a new result")
    ] = False,
    baselines: Annotated[
        bool,
        typer.Option(
            "--baselines/--no-baselines",
            help="expand assigned prompt-only primary baselines before freezing the invocation",
        ),
    ] = True,
) -> None:
    """Run exact recipe versions on one already-frozen source."""
    from uuid import UUID

    import psycopg

    from altiscope import __version__
    from altiscope.comparison.service import run_comparison
    from altiscope.store.db import connect

    settings = load_settings()
    try:
        parsed_source = UUID(source_id)
        parsed_recipes = tuple(UUID(value) for value in recipes)
        with connect(settings.database_url) as conn:
            run = run_comparison(
                conn,
                source_id=parsed_source,
                recipe_version_ids=parsed_recipes,
                retention=settings.llm_payload_retention,
                execution_build=__version__,
                regenerate=regenerate,
                include_primary_baselines=baselines,
            )
    except (ValueError, OSError, psycopg.Error) as exc:
        typer.echo(f"Could not run comparison: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Comparison invocation {run.invocation.id}")
    for member in run.members:
        current_cost = (
            f"configured-price estimate ${member.current.estimated_cost_usd:.8f}"
            if member.current.cost_status == "complete"
            else member.current.cost_status
        )
        line = (
            f"  {member.condition_label}: {member.recipe.name} v{member.recipe.version}; "
            f"{member.disposition} result {member.result.id} ({member.result.status}); "
            f"new calls {member.current.call_count}, current cost {current_cost}"
        )
        if member.result.error_code is not None:
            line += f"; error {member.result.error_code}"
            if member.result.error_message is not None:
                line += f": {member.result.error_message}"
        if member.disposition == "reused":
            origin_cost = (
                f"configured-price estimate ${member.origin.estimated_cost_usd:.8f}"
                if member.origin.cost_status == "complete"
                else member.origin.cost_status
            )
            line += (
                f"; origin calls {member.origin.call_count}, origin cost {origin_cost}, "
                f"origin model latency {member.origin.model_latency_ms} ms, "
                f"origin retention {member.result.origin_retention}"
            )
            if (
                run.invocation.retention == "full"
                and member.result.origin_retention == "hashes_only"
            ):
                line += "; use --regenerate to retain new raw payloads"
        typer.echo(line)
    total_cost = (
        f"configured-price estimate ${run.new_estimated_cost_usd:.8f}"
        if run.new_cost_status == "complete"
        else run.new_cost_status
    )
    typer.echo(
        f"Current invocation: {run.new_call_count} model calls; cost {total_cost}; "
        f"elapsed {run.elapsed_ms} ms"
    )


@comparisons_app.command("assess")
def comparisons_assess(
    result_id: Annotated[str, typer.Argument(help="exact successful comparison-result UUID")],
    recipe: Annotated[str, typer.Option(help="exact independent verify recipe-version UUID")],
    reveal: Annotated[
        bool,
        typer.Option(
            help="show the verdict and rationale; default output is safe for pre-judgment use"
        ),
    ] = False,
) -> None:
    """Assess one exact result and its exact saved source without routing or refresh."""
    from uuid import UUID

    import psycopg

    from altiscope.assessment import render_assessment, run_assessment
    from altiscope.store.db import connect

    settings = load_settings()
    try:
        parsed_result = UUID(result_id)
        parsed_recipe = UUID(recipe)
        with connect(settings.database_url) as conn:
            run = run_assessment(
                conn,
                target_result_id=parsed_result,
                assessor_recipe_version_id=parsed_recipe,
                retention=settings.llm_payload_retention,
            )
    except (ValueError, OSError, psycopg.Error) as exc:
        typer.echo(f"Could not run assessment: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(render_assessment(run.assessment, reveal=reveal), nl=False)
    cost = (
        f"configured-price estimate ${run.measurements.estimated_cost_usd:.8f}"
        if run.measurements.cost_status == "complete"
        else run.measurements.cost_status
    )
    typer.echo(f"Assessment calls: {run.measurements.call_count}; cost {cost}")


@comparisons_app.command("review")
def comparisons_review(  # noqa: PLR0917
    result_id: Annotated[str, typer.Argument(help="exact successful comparison-result UUID")],
    reviewer: Annotated[str, typer.Option(prompt=True, help="study reviewer identifier")],
    case_id: Annotated[str, typer.Option(prompt=True, help="protocol case identifier")],
    case_group: Annotated[
        str, typer.Option(help="development or held_out; development is for workflow tuning")
    ] = "development",
    reader_role: Annotated[str | None, typer.Option(help="ic, manager, or exec")] = None,
    familiarity: Annotated[
        str, typer.Option(help="direct, repository, domain, prepared, or none")
    ] = "domain",
    familiarity_basis: Annotated[
        str, typer.Option(prompt=True, help="short qualification basis")
    ] = "",
    prior_exposure: Annotated[
        str, typer.Option(help="none_declared, known, or unknown")
    ] = "none_declared",
    prior_assessment: Annotated[
        str | None, typer.Option(help="exact already-seen assessment UUID, when known")
    ] = None,
    invocation_id: Annotated[
        str | None, typer.Option(help="invocation that presented this exact result")
    ] = None,
    result_presentation_ordinal: Annotated[
        int, typer.Option(help="actual result presentation position")
    ] = 1,
    evaluation_dir: Annotated[
        Path, typer.Option(help="directory containing the versioned M3 evaluation documents")
    ] = Path("docs/evaluation"),
) -> None:
    """Inspect frozen evidence, then commit an initial judgment before any guided reveal."""
    from datetime import UTC, datetime
    from uuid import UUID

    import psycopg

    from altiscope.assessment import render_assessment
    from altiscope.review.workflow import retain_protocol_artifacts
    from altiscope.store.comparisons import list_assessments, load_result, load_source
    from altiscope.store.db import connect
    from altiscope.store.evaluation import (
        create_review_session,
        record_exposure,
    )

    if case_group not in ("development", "held_out"):
        raise typer.BadParameter("case-group must be development or held_out")
    if familiarity not in ("direct", "repository", "domain", "prepared", "none"):
        raise typer.BadParameter(
            "familiarity must be direct, repository, domain, prepared, or none"
        )
    if prior_exposure not in ("none_declared", "known", "unknown"):
        raise typer.BadParameter("prior-exposure must be none_declared, known, or unknown")
    if prior_assessment is not None and prior_exposure != "known":
        raise typer.BadParameter("prior-assessment requires --prior-exposure known")
    try:
        parsed_result = UUID(result_id)
        parsed_invocation = UUID(invocation_id) if invocation_id else None
        with connect(load_settings().database_url) as conn:
            result = load_result(conn, parsed_result)
            source = load_source(conn, result.source_id)
            role = reader_role or ("ic" if source.kind == "pr" else "manager")
            if role not in ("ic", "manager", "exec"):
                raise ValueError("reader role must be ic, manager, or exec")
            artifacts = retain_protocol_artifacts(conn, evaluation_dir=evaluation_dir)
            session = create_review_session(
                conn,
                result_id=parsed_result,
                reviewer_id=reviewer,
                protocol_artifact_id=artifacts.protocol_id,
                dataset_artifact_id=artifacts.dataset_id,
                record_contract_artifact_id=artifacts.record_contract_id,
                case_id=case_id,
                case_kind=source.kind,
                case_group=case_group,
                reader_role=role,
                familiarity_level=familiarity,
                familiarity_basis=familiarity_basis,
                declared_prior_exposure=prior_exposure,
                result_presentation_ordinal=result_presentation_ordinal,
                started_at=datetime.now(UTC),
                invocation_id=parsed_invocation,
            )
            if prior_assessment is not None:
                record_exposure(
                    conn,
                    review_session_id=session.id,
                    assessment_id=UUID(prior_assessment),
                    kind="declared_prior_external",
                    presentation_ordinal=1,
                    occurred_at=datetime.now(UTC),
                )

            typer.echo(f"Review session {session.id}; assessment output remains hidden.")
            _capture_initial_revision(conn, session.id)
            assessments = list_assessments(conn, target_result_id=parsed_result)
            if assessments:
                typer.echo("Available assessment records (content concealed):")
                for assessment in assessments:
                    typer.echo(render_assessment(assessment, reveal=False), nl=False)
                typer.echo(
                    f"Reveal explicitly: altiscope reviews reveal {session.id} ASSESSMENT_UUID"
                )
            else:
                typer.echo("Assessment status: not_run")
            typer.echo(f"Resume: altiscope reviews show {session.id}")
    except (ValueError, OSError, psycopg.Error) as exc:
        typer.echo(f"Could not record review: {exc}", err=True)
        raise typer.Exit(1) from None


@reviews_app.command("resume")
def reviews_resume(review_session_id: str) -> None:
    """Resume an interrupted session that has not committed its initial judgment."""
    import psycopg

    from altiscope.assessment import render_assessment
    from altiscope.store.comparisons import list_assessments
    from altiscope.store.db import connect
    from altiscope.store.evaluation import load_review_record

    try:
        session_id = UUID(review_session_id)
        with connect(load_settings().database_url) as conn:
            record = load_review_record(conn, session_id)
            _capture_initial_revision(conn, session_id)
            result_id = UUID(str(record["result_id"]))
            assessments = list_assessments(conn, target_result_id=result_id)
            if assessments:
                typer.echo("Available assessment records (content concealed):")
                for assessment in assessments:
                    typer.echo(render_assessment(assessment, reveal=False), nl=False)
                typer.echo(
                    f"Reveal explicitly: altiscope reviews reveal {session_id} ASSESSMENT_UUID"
                )
            else:
                typer.echo("Assessment status: not_run")
    except (ValueError, psycopg.Error) as exc:
        typer.echo(f"Could not resume review: {exc}", err=True)
        raise typer.Exit(1) from None


@reviews_app.command("show")
def reviews_show(
    review_session_id: str,
    json_output: Annotated[bool, typer.Option("--json", help="emit the reloadable record")] = False,
) -> None:
    """Reload a review; reveal only assessments already recorded as exposed."""
    from uuid import UUID

    import psycopg

    from altiscope.assessment import render_assessment
    from altiscope.review import render_frozen_source, render_review_result
    from altiscope.store.comparisons import list_assessments, load_result, load_source
    from altiscope.store.db import connect
    from altiscope.store.evaluation import load_review_record

    try:
        with connect(load_settings().database_url) as conn:
            record = load_review_record(conn, UUID(review_session_id))
            if json_output:
                typer.echo(json.dumps(record, indent=2, sort_keys=True))
                return
            result = load_result(conn, UUID(str(record["result_id"])))
            source = load_source(conn, result.source_id)
            typer.echo(
                f"Review session {review_session_id}; result {result.id}; reviewer "
                f"{record['reviewer_id']}"
            )
            typer.echo(render_frozen_source(source), nl=False)
            typer.echo(render_review_result(result), nl=False)
            exposed = {
                str(item["assessment_id"])
                for item in cast(list[dict[str, object]], record["exposures"])
            }
            assessments = list_assessments(conn, target_result_id=result.id)
            if not assessments:
                typer.echo("Assessment status: not_run")
            for assessment in assessments:
                typer.echo(
                    render_assessment(assessment, reveal=str(assessment.id) in exposed), nl=False
                )
            typer.echo(
                f"Revisions: {len(cast(list[object], record['revisions']))}; "
                f"exposures: {len(exposed)}; completed: {record['completed_at'] or 'no'}"
            )
    except (ValueError, psycopg.Error) as exc:
        typer.echo(f"Could not load review: {exc}", err=True)
        raise typer.Exit(1) from None


@reviews_app.command("reveal")
def reviews_reveal(
    review_session_id: str,
    assessment_id: str,
    presentation_ordinal: Annotated[int, typer.Option(help="actual assessment position")] = 1,
    kind: Annotated[
        str, typer.Option(help="guided_reveal, accidental, or general_inspection")
    ] = "guided_reveal",
) -> None:
    """Persist exposure first, then display the exact assessment verdict and rationale."""
    from datetime import UTC, datetime
    from uuid import UUID

    import psycopg

    from altiscope.assessment import render_assessment
    from altiscope.store.comparisons import load_assessment
    from altiscope.store.db import connect
    from altiscope.store.evaluation import record_exposure

    if kind not in ("guided_reveal", "accidental", "general_inspection"):
        raise typer.BadParameter("kind must be guided_reveal, accidental, or general_inspection")
    try:
        with connect(load_settings().database_url) as conn:
            exposure_id = record_exposure(
                conn,
                review_session_id=UUID(review_session_id),
                assessment_id=UUID(assessment_id),
                kind=cast(
                    Literal[
                        "guided_reveal",
                        "declared_prior_external",
                        "accidental",
                        "general_inspection",
                    ],
                    kind,
                ),
                presentation_ordinal=presentation_ordinal,
                occurred_at=datetime.now(UTC),
            )
            assessment = load_assessment(conn, UUID(assessment_id))
        typer.echo(f"Exposure {exposure_id} committed before display.")
        typer.echo(render_assessment(assessment, reveal=True), nl=False)
        typer.echo(
            f"Record its effect: altiscope reviews observe {review_session_id} {exposure_id}"
        )
    except (ValueError, psycopg.Error) as exc:
        typer.echo(f"Could not reveal assessment: {exc}", err=True)
        raise typer.Exit(1) from None


@reviews_app.command("observe")
def reviews_observe(
    review_session_id: str,
    exposure_id: str,
    revise_judgment: Annotated[
        bool, typer.Option(help="append a post-assessment judgment revision")
    ] = False,
    complete: Annotated[bool, typer.Option(help="mark the review session complete")] = False,
) -> None:
    """Record assessment effects, extra effort, usefulness, and an optional revision."""
    from datetime import UTC, datetime
    from uuid import UUID

    import psycopg

    from altiscope.review.workflow import assessment_observation_state
    from altiscope.store.comparisons import load_assessment
    from altiscope.store.db import connect
    from altiscope.store.evaluation import (
        ReviewRevisionInput,
        append_review_revision,
        complete_review_session,
        load_exposure_assessment_id,
        record_post_assessment_observation,
    )

    try:
        session_uuid = UUID(review_session_id)
        exposure_uuid = UUID(exposure_id)
        with connect(load_settings().database_url) as conn:
            assessment_id = load_exposure_assessment_id(
                conn, review_session_id=session_uuid, exposure_id=exposure_uuid
            )
            assessment = load_assessment(conn, assessment_id)
            observation_status = assessment_observation_state(assessment.status)
            rationale = typer.prompt("Assessment observation rationale")
            assessment_effort = _prompt_effort("assessment_related")
            post_status, post_score, post_rationale = _prompt_usefulness("Post-assessment")
            true_detection: bool | None = None
            false_alarm: bool | None = None
            missed_problem: bool | None = None
            inconclusive: bool | None = None
            if observation_status in ("succeeded", "inconclusive"):
                true_detection = typer.confirm("Accepted true problem detection?", default=False)
                false_alarm = typer.confirm("Rejected false alarm?", default=False)
                missed_problem = typer.confirm(
                    "Material problem missed by assessment?", default=False
                )
                inconclusive = typer.confirm(
                    "Observation remains inconclusive?",
                    default=observation_status == "inconclusive",
                )

            resulting_revision_id = None
            if revise_judgment:
                correctness = _prompt_choice(
                    "Revised whole-result correctness",
                    ("correct", "incorrect", "unclear"),
                    default="correct",
                )
                correctness_rationale = typer.prompt(
                    "Revised correctness rationale (optional)", default="", show_default=False
                ).strip()
                correction = typer.prompt(
                    "Revised corrected account text (blank for none)",
                    default="",
                    show_default=False,
                ).strip()
                correction_effort = (
                    _prompt_effort("correction")
                    if correction
                    else EffortMeasure(component="correction", status="not_applicable")
                )
                exposure_rows = conn.execute(
                    "SELECT id FROM assessment_exposures WHERE review_session_id=%s "
                    "ORDER BY ordinal",
                    (session_uuid,),
                ).fetchall()
                resulting_revision_id = append_review_revision(
                    conn,
                    review_session_id=session_uuid,
                    revision=ReviewRevisionInput(
                        kind="post_assessment",
                        blind_status="known_exposed",
                        correctness_label=cast(
                            Literal["correct", "incorrect", "unclear"], correctness
                        ),
                        correctness_rationale=correctness_rationale or None,
                        correction=correction or None,
                        usefulness_status=cast(
                            Literal["measured", "unavailable", "not_applicable"], post_status
                        ),
                        usefulness_score=post_score,
                        usefulness_rationale=post_rationale,
                        effort=(correction_effort,),
                        created_at=datetime.now(UTC),
                    ),
                    exposure_ids_seen=tuple(UUID(str(item[0])) for item in exposure_rows),
                )
            record_post_assessment_observation(
                conn,
                review_session_id=session_uuid,
                exposure_id=exposure_uuid,
                assessment_id=assessment.id,
                assessment_status=cast(
                    Literal["not_run", "failed", "inconclusive", "succeeded"],
                    observation_status,
                ),
                assessment_verdict=assessment.verdict,
                rationale=rationale,
                assessment_related_effort=assessment_effort,
                post_usefulness_status=cast(
                    Literal["measured", "unavailable", "not_applicable"], post_status
                ),
                post_usefulness_score=post_score,
                post_usefulness_rationale=post_rationale,
                true_problem_detection=true_detection,
                false_alarm=false_alarm,
                missed_problem=missed_problem,
                inconclusive=inconclusive,
                resulting_revision_id=resulting_revision_id,
            )
            if complete:
                complete_review_session(conn, session_uuid, datetime.now(UTC))
        typer.echo(
            "Assessment observation committed"
            + (f" with revision {resulting_revision_id}" if resulting_revision_id else "")
            + "."
        )
    except (ValueError, psycopg.Error) as exc:
        typer.echo(f"Could not record observation: {exc}", err=True)
        raise typer.Exit(1) from None


@reviews_app.command("complete")
def reviews_complete(review_session_id: str) -> None:
    """Mark a durable review session complete without changing any revision."""
    from datetime import UTC, datetime
    from uuid import UUID

    import psycopg

    from altiscope.store.db import connect
    from altiscope.store.evaluation import complete_review_session

    try:
        with connect(load_settings().database_url) as conn:
            complete_review_session(conn, UUID(review_session_id), datetime.now(UTC))
        typer.echo(f"Review session {review_session_id} completed.")
    except (ValueError, psycopg.Error) as exc:
        typer.echo(f"Could not complete review: {exc}", err=True)
        raise typer.Exit(1) from None


@reviews_app.command("export")
def reviews_export(
    review_session_id: str,
    output: Annotated[
        Path | None, typer.Option(help="write JSON to this path; default is standard output")
    ] = None,
) -> None:
    """Export the complete reloadable m3-review-record-v1 document."""
    from uuid import UUID

    import psycopg

    from altiscope.store.db import connect
    from altiscope.store.evaluation import export_review_record

    try:
        with connect(load_settings().database_url) as conn:
            record = export_review_record(conn, UUID(review_session_id))
        rendered = json.dumps(record, indent=2, sort_keys=True) + "\n"
        if output is None:
            typer.echo(rendered, nl=False)
        else:
            output.write_text(rendered)
            typer.echo(f"Exported review session {review_session_id} to {output}")
    except (ValueError, OSError, psycopg.Error) as exc:
        typer.echo(f"Could not export review: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command()
def ingest(repository: str, number: int) -> None:
    """Collect one public PR, including all discussion, into immutable storage."""
    from altiscope.ingest.github.pat import PatClient
    from altiscope.store.db import connect
    from altiscope.store.snapshots import save_snapshot

    settings = load_settings()
    client = PatClient(settings.github_token, base_url=settings.github_api_base)
    try:
        typer.echo(f"Collecting {repository}#{number} from GitHub ...", err=True)
        snapshot = client.fetch_pull_request(repository, number)
        with connect(settings.database_url) as conn:
            stored = save_snapshot(
                conn,
                snapshot,
                repository_id=int(client.repository_metadata["id"]),
                default_branch=client.repository_metadata["default_branch"],
                raw=client.raw,
            )
        typer.echo(f"Stored {repository}#{number} snapshot {stored.version} (id {stored.id})")
    except (ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    finally:
        client.close()


@app.command()
def summarize(repository: str, number: int) -> None:
    """Generate and save a report for a merged PR, preserving earlier versions."""
    from altiscope.prompts import latest_prompt
    from altiscope.store.db import connect
    from altiscope.store.snapshots import load_snapshot
    from altiscope.summarize.service import summarize as run_summary

    settings = load_settings()
    with connect(settings.database_url) as conn:
        stored = load_snapshot(conn, repository, number)
        registry = Registry.load(settings.models_config)
        typer.echo(
            f"Summarizing {repository}#{number} via {registry.stages['pr_summary'].candidates[0]} "
            f"({registry.provider_for(registry.stages['pr_summary'].candidates[0]).name}) ...",
            err=True,
        )
        summary_id = run_summary(
            conn,
            stored,
            registry=registry,
            prompt=latest_prompt(settings.prompts_dir, "pr_summary"),
            retention=settings.llm_payload_retention,
        )
    typer.echo(f"Account {summary_id}; use show to inspect review status and PR provenance.")


@app.command()
def show(
    repository: str,
    number: int,
    verbose: Annotated[bool, typer.Option(help="Show PR provenance, facts, and omissions")] = False,
) -> None:
    """Inspect the latest snapshot's account, sources, computed facts and omissions."""
    from altiscope.store.accounts import account_provenance, load_account, load_account_context
    from altiscope.store.db import connect
    from altiscope.store.snapshots import load_snapshot
    from altiscope.summarize.publication import render_account

    settings = load_settings()
    with connect(settings.database_url) as conn:
        stored = load_snapshot(conn, repository, number)
        ctx = load_account_context(conn, stored.id, stored.snapshot)
        publication = load_account(conn, stored.id, ctx)
        provenance = account_provenance(conn, stored.id)
    if verbose:
        typer.echo(f"Snapshot version: {stored.version}; id: {stored.id}")
        typer.echo(provenance)
    typer.echo(render_account(publication, ctx, verbose=verbose), nl=False)


@app.command()
def demo(
    stage: Annotated[str, typer.Option(help="pr_summary or aggregate")] = "pr_summary",
    multi_level: Annotated[
        bool, typer.Option(help="Use a small context budget for the aggregate demo")
    ] = False,
    altitude: Annotated[str, typer.Option(help="ic, manager, or exec")] = "manager",
    persist: Annotated[bool, typer.Option(help="Also exercise Postgres storage")] = False,
) -> None:
    """Replay the checked-in synthetic fixture through the same generation services."""
    from pathlib import Path

    from altiscope.ingest.snapshot import PullRequestSnapshot
    from altiscope.prompts import latest_prompt
    from altiscope.summarize.fixture import FixtureProvider, fixture_registry
    from altiscope.summarize.generate import generate_account
    from altiscope.summarize.publication import render_account
    from altiscope.summarize.service import prepare

    if stage == "aggregate":
        import psycopg

        from altiscope.aggregate.demo import run_demo
        from altiscope.aggregate.planner import PlanningError

        try:
            typer.echo(run_demo(altitude, persist=persist, multi_level=multi_level), nl=False)
        except (ValueError, RuntimeError, PlanningError, RoutingError, psycopg.Error) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from None
        return
    if stage != "pr_summary":
        raise typer.BadParameter("stage must be pr_summary or aggregate")
    settings = load_settings()
    root = Path("examples/m1")
    snapshot = PullRequestSnapshot.model_validate_json((root / "snapshot.json").read_text())
    ctx = prepare(snapshot)
    registry = fixture_registry()
    model = registry.models["fixture"]
    generated = generate_account(
        ctx,
        FixtureProvider([(root / "response.json").read_text()]),
        model,
        system=latest_prompt(settings.prompts_dir, "pr_summary").body,
        max_tokens=4096,
        effort="low",
        input_budget=100000,
    )
    if persist:
        from altiscope.llm.router import route
        from altiscope.store.accounts import load_account, save_account
        from altiscope.store.db import connect
        from altiscope.store.snapshots import save_snapshot
        from altiscope.summarize.context import render_user_prompt
        from altiscope.summarize.generate import request_tokens

        prompt = latest_prompt(settings.prompts_dir, "pr_summary")
        with connect(settings.database_url) as conn:
            stored = save_snapshot(
                conn,
                snapshot,
                repository_id=9000000000000042,
                default_branch="main",
                raw={"fixture": True},
            )
            decision = route(
                registry, "pr_summary", request_tokens(prompt.body, render_user_prompt(ctx))
            )
            save_account(
                conn,
                stored.id,
                ctx,
                generated=generated,
                prompt=prompt,
                decision=decision,
                registry=registry,
                retention=settings.llm_payload_retention,
            )
            publication = load_account(conn, stored.id, ctx)
    else:
        publication = generated.publication
    typer.echo("SYNTHETIC FIXTURE DEMO — recorded response, no live model call.")
    typer.echo(render_account(publication, ctx), nl=False)


@app.command("aggregate")
def aggregate_command(
    repository: str,
    *,
    since: Annotated[str, typer.Option(help="First UTC date, YYYY-MM-DD")],
    until: Annotated[str, typer.Option(help="Last UTC date, inclusive, YYYY-MM-DD")],
    altitude: Annotated[str, typer.Option(help="ic, manager, or exec")] = "manager",
    local_only: Annotated[
        bool, typer.Option(help="Use saved sources without checking GitHub")
    ] = False,
    regenerate: Annotated[
        bool, typer.Option(help="Generate new aggregate versions, bypassing cache")
    ] = False,
) -> None:
    """Summarize merged PR reports for a repository and date window."""
    from datetime import UTC, date, datetime, time

    import psycopg

    from altiscope.aggregate.planner import PlanningError
    from altiscope.aggregate.resolve import resolve_reports
    from altiscope.aggregate.service import AggregateQuery, aggregate_reports
    from altiscope.ingest.github.pat import PatClient
    from altiscope.prompts import latest_prompt
    from altiscope.schemas.aggregate import Altitude
    from altiscope.store.aggregates import PostgresAggregateStore
    from altiscope.store.db import connect

    client = None
    try:
        query = AggregateQuery(
            repository=repository,
            since=datetime.combine(date.fromisoformat(since), time.min, UTC),
            until=datetime.combine(date.fromisoformat(until), time.max, UTC),
            altitude=Altitude.from_str(altitude),
        )
        settings = load_settings()
        registry = Registry.load(settings.models_config)
        if local_only:
            typer.echo(
                "Using saved sources only; GitHub completeness and freshness are not checked.",
                err=True,
            )
        else:
            typer.echo("Refreshing repository PRs from GitHub ...", err=True)
            client = PatClient(settings.github_token, base_url=settings.github_api_base)
        with connect(settings.database_url) as conn:
            # Each snapshot/report is durable independently, including failed attempts.
            conn.autocommit = True
            inputs = resolve_reports(
                conn,
                query,
                registry=registry,
                prompt=latest_prompt(settings.prompts_dir, "pr_summary"),
                retention=settings.llm_payload_retention,
                client=client,
            )
            result = aggregate_reports(
                inputs,
                query=query,
                store=PostgresAggregateStore(conn),
                registry=registry,
                prompt=latest_prompt(settings.prompts_dir, "aggregate"),
                retention=settings.llm_payload_retention,
                force=regenerate,
            )
        if result.report is None:
            typer.echo("0 PRs merged in this window. No model call needed.")
        else:
            typer.echo(
                f"Aggregate {result.report.id}; aggregate model calls: {result.calls}; "
                f"cached reports: {result.cache_hits}"
            )
            typer.echo(f"Inspect: altiscope show-aggregate {result.report.id}")
    except (ValueError, RuntimeError, RoutingError, PlanningError, psycopg.Error, OSError) as exc:
        typer.echo(f"Could not aggregate: {exc}", err=True)
        raise typer.Exit(1) from None
    finally:
        if client is not None:
            client.close()


@app.command("show-aggregate")
def show_aggregate(
    report_id: str,
    verbose: Annotated[
        bool, typer.Option(help="Include model, exact prompt, settings, and call history")
    ] = False,
) -> None:
    """Inspect a saved aggregate and the exact report versions it used."""
    from uuid import UUID

    import psycopg

    from altiscope.aggregate.render import render_aggregate
    from altiscope.store.aggregates import PostgresAggregateStore
    from altiscope.store.db import connect

    try:
        with connect(load_settings().database_url) as conn:
            report = PostgresAggregateStore(conn).get(report_id)
            typer.echo(render_aggregate(report, verbose=verbose), nl=False)
            if verbose:
                rows = conn.execute(
                    "SELECT c.id,c.provider,c.model_id,c.started_at,c.stop_reason,c.error "
                    "FROM aggregate_report_calls a JOIN llm_calls c ON c.id=a.call_id "
                    "WHERE a.report_id=%s ORDER BY c.id",
                    (UUID(report_id),),
                ).fetchall()
                typer.echo("Model-call attempts:")
                for row in rows:
                    typer.echo(
                        f"  {row[0]}: {row[1]}/{row[2]} at {row[3]}; {row[4]}"
                        + (f"; {row[5]}" if row[5] else "")
                    )
    except (ValueError, psycopg.Error) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None


@app.command("show-report")
def show_report(
    report_id: int,
    verbose: Annotated[
        bool, typer.Option(help="Include saved facts, input exclusions, and exact prompt")
    ] = False,
) -> None:
    """Inspect a specific historical PR report, even after it has been regenerated."""
    import json

    import psycopg

    from altiscope.store.db import connect

    try:
        with connect(load_settings().database_url) as conn:
            row = conn.execute(
                "SELECT s.narrative,p.html_url,p.snapshot_version,"
                "c.provider,c.model_id,c.started_at,"
                "v.name,v.source_text,s.facts,s.input_manifest,p.normalized_snapshot "
                "FROM pr_summaries s JOIN pull_requests p ON p.id=s.pull_request_id "
                "JOIN llm_calls c ON c.id=s.llm_call_id "
                "JOIN prompt_versions v ON v.id=s.prompt_version_id "
                "WHERE s.id=%s AND s.status='published'",
                (report_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Published PR report not found")
        typer.echo(f"PR report {report_id}; snapshot version {row[2]}")
        typer.echo(row[1])
        typer.echo(f"Author: {row[10].get('author_login', 'unknown')}")
        typer.echo(f"Provider: {row[3]}; model: {row[4]}; generated: {row[5]}; prompt: {row[6]}")
        typer.echo(row[0])
        if verbose:
            typer.echo("Saved facts and input exclusions:")
            typer.echo(
                json.dumps(dict(facts=row[8], input_manifest=row[9]), indent=2, sort_keys=True)
            )
            typer.echo("Exact prompt file:")
            typer.echo(row[7])
    except (ValueError, psycopg.Error) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
