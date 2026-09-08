"""Shared snapshot-to-account orchestration for the CLI and demonstrations."""

from __future__ import annotations

import psycopg

from altiscope.ingest.diff_policy import apply, manifest
from altiscope.ingest.snapshot import PrState, PullRequestSnapshot
from altiscope.llm.provider import Provider
from altiscope.llm.providers import ProviderPool
from altiscope.llm.registry import Registry
from altiscope.llm.router import route
from altiscope.prompts import Prompt
from altiscope.store.accounts import save_account
from altiscope.store.snapshots import StoredSnapshot
from altiscope.summarize.context import PrContext, build_context, render_user_prompt
from altiscope.summarize.facts import compute_facts
from altiscope.summarize.generate import generate_account, request_tokens


def prepare(snapshot: PullRequestSnapshot) -> PrContext:
    outcome = apply(snapshot.files)
    return build_context(snapshot, outcome, compute_facts(snapshot, outcome), manifest(outcome))


def summarize(
    conn: psycopg.Connection,
    stored: StoredSnapshot,
    *,
    registry: Registry,
    prompt: Prompt,
    retention: str,
    provider: Provider | None = None,
) -> int:
    if stored.snapshot.state != PrState.merged:
        raise ValueError("Only merged pull requests can be summarized in M1")
    if prompt.schema_version != 2:
        raise ValueError("The M1 account requires schema version 2")
    ctx = prepare(stored.snapshot)
    decision = route(registry, "pr_summary", request_tokens(prompt.body, render_user_prompt(ctx)))
    selected = provider or ProviderPool(registry).for_model(decision.model_id)
    generated = generate_account(
        ctx,
        selected,
        registry.models[decision.model_id],
        system=prompt.body,
        max_tokens=registry.stages["pr_summary"].reserved_output_tokens,
        effort=decision.effort,
        input_budget=registry.input_budget(decision.model_id, "pr_summary"),
    )
    return save_account(
        conn,
        stored.id,
        ctx,
        generated=generated,
        prompt=prompt,
        decision=decision,
        registry=registry,
        retention=retention,
    )
