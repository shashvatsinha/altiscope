"""Save model attempts and publish reviews linked to their immutable PR snapshot."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from altiscope.ingest.diff_policy import InputManifest
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.llm.registry import Registry
from altiscope.llm.router import RoutingDecision
from altiscope.prompts import Prompt
from altiscope.schemas.pr_summary import PrReviewOutput
from altiscope.store.snapshots import insert
from altiscope.summarize.context import PrContext
from altiscope.summarize.facts import PrFacts
from altiscope.summarize.generate import GeneratedAccount, request_tokens
from altiscope.summarize.publication import Publication, PublicationState, assess


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def save_account(
    conn: psycopg.Connection,
    snapshot_id: int,
    ctx: PrContext,
    *,
    generated: GeneratedAccount,
    prompt: Prompt,
    decision: RoutingDecision,
    registry: Registry,
    retention: str,
) -> int:
    if not generated.attempts:
        raise ValueError("; ".join(generated.publication.errors))
    model = registry.models[decision.model_id]
    with conn.transaction():
        row = conn.execute(
            "SELECT normalized_snapshot FROM pull_requests WHERE id=%s FOR UPDATE", (snapshot_id,)
        ).fetchone()
        if row is None or row[0] != ctx.snapshot.model_dump(mode="json"):
            raise ValueError("Context does not match stored snapshot")
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
        for ordinal, attempt in enumerate(generated.attempts, 1):
            result = attempt.result
            request = dict(
                system=prompt.body,
                user=attempt.user,
                schema=PrReviewOutput.model_json_schema(),
                model=model.wire_name,
                effort=decision.effort,
                output_mode=result.output_mode,
                max_tokens=registry.stages["pr_summary"].reserved_output_tokens,
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
                    stage="pr_summary",
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
                    estimated_input_tokens=request_tokens(prompt.body, attempt.user),
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
                            stage=registry.stages["pr_summary"].model_dump(mode="json"),
                            output_mode=result.output_mode,
                            input_budget_fraction=registry.input_budget_fraction,
                        )
                    ),
                    started_at=attempt.started_at,
                    finished_at=attempt.finished_at,
                ),
            )
        checked = assess(generated.publication.output)
        published = checked.state == PublicationState.published
        # A failed rerun must not replace the current published account.
        if published:
            conn.execute(
                "UPDATE pr_summaries SET is_current=false WHERE pull_request_id=%s", (snapshot_id,)
            )
        summary_id = insert(
            conn,
            "pr_summaries",
            dict(
                pull_request_id=snapshot_id,
                llm_call_id=call_id,
                prompt_version_id=prompt_id,
                schema_version=prompt.schema_version,
                model_id=model.id,
                is_current=published,
                status="published" if published else "needs_review",
                headline="",
                narrative=checked.output.review if checked.output else "",
                facts=Jsonb(ctx.facts.model_dump(mode="json")),
                input_manifest=Jsonb(ctx.manifest.model_dump(mode="json")),
            ),
        )
        return summary_id


def load_account(conn: psycopg.Connection, snapshot_id: int, ctx: PrContext) -> Publication:
    row = conn.execute(
        "SELECT s.id,s.status,c.provider,c.model_id,c.stop_reason,c.error,"
        "s.narrative,s.schema_version "
        "FROM pr_summaries s JOIN llm_calls c ON c.id=s.llm_call_id "
        "WHERE s.pull_request_id=%s ORDER BY s.is_current DESC,s.id DESC LIMIT 1",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise ValueError("No account exists; run summarize first")
    if row[1] != "published":
        _, _, provider, model_id, stop_reason, error, _, _ = row
        detail = error or f"model call ended with {stop_reason}"
        return Publication(
            PublicationState.needs_review,
            None,
            (f"Generated account withheld: {provider}/{model_id}: {detail}",),
        )
    return assess(PrReviewOutput(review=row[6]))


def account_provenance(conn: psycopg.Connection, snapshot_id: int) -> str:
    row = conn.execute(
        "SELECT c.provider,c.model_id,p.name,p.content_hash,s.schema_version "
        "FROM pr_summaries s JOIN llm_calls c ON c.id=s.llm_call_id "
        "JOIN prompt_versions p ON p.id=s.prompt_version_id "
        "WHERE s.pull_request_id=%s ORDER BY s.is_current DESC,s.id DESC LIMIT 1",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise ValueError("No account exists; run summarize first")
    label = "RECORDED FIXTURE; no live model call.\n" if row[0] == "fixture" else ""
    return (
        label
        + f"Provider: {row[0]}; model: {row[1]}; prompt: {row[2]}; schema: {row[4]}\n"
        + (f"Prompt hash: {row[3]}")
    )


def load_account_context(
    conn: psycopg.Connection,
    snapshot_id: int,
    snapshot: PullRequestSnapshot,
) -> PrContext:
    """Use the published facts and manifest, not today's potentially changed policy."""
    row = conn.execute(
        "SELECT facts,input_manifest FROM pr_summaries WHERE pull_request_id=%s "
        "ORDER BY is_current DESC,id DESC LIMIT 1",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise ValueError("No account exists; run summarize first")
    facts = PrFacts.model_validate(row[0])
    manifest = InputManifest.model_validate(row[1])
    return PrContext(snapshot, facts, manifest)
