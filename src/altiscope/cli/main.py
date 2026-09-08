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
app.add_typer(db_app, name="db")
app.add_typer(models_app, name="models")
app.add_typer(prompts_app, name="prompts")


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
        typer.echo(
            f"  {spec.id:<20} {spec.provider:<10} ctx={spec.context_window:>9,} "
            f"out={spec.max_output_tokens:>7,} "
            f"${spec.input_usd_per_mtok}/${spec.output_usd_per_mtok} per MTok  "
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
    """Generate and store a citation-checked account of a merged PR."""
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
    typer.echo(f"Account {summary_id}; use show to inspect publication status and evidence.")


@app.command()
def show(
    repository: str,
    number: int,
    verbose: Annotated[
        bool, typer.Option(help="Show evidence, provenance, facts, and omissions")
    ] = False,
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


if __name__ == "__main__":
    app()
