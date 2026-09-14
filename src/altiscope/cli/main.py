"""The `altiscope` command."""

from __future__ import annotations

from typing import Annotated

import typer

from altiscope.config import load_settings
from altiscope.llm.registry import Registry
from altiscope.llm.router import RoutingError, route
from altiscope.llm.types import STAGES, Stage
from altiscope.prompts import list_prompts

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
app.add_typer(db_app, name="db")
app.add_typer(models_app, name="models")
app.add_typer(prompts_app, name="prompts")
app.add_typer(recipes_app, name="recipes")
app.add_typer(comparisons_app, name="comparisons")


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
