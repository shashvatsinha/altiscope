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
    help="Altitude-appropriate visibility into engineering work.", no_args_is_help=True
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


if __name__ == "__main__":
    app()
