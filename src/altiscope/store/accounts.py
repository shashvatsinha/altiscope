"""Save model attempts and publish claims with same-snapshot evidence ownership."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from altiscope.ingest.diff_policy import FileDecision, InputManifest, PolicyOutcome
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.llm.registry import Registry
from altiscope.llm.router import RoutingDecision
from altiscope.prompts import Prompt
from altiscope.schemas.pr_summary import Evidence, EvidenceType, PrAccountOutput
from altiscope.store.snapshots import insert
from altiscope.summarize.context import PrContext, build_context
from altiscope.summarize.facts import PrFacts
from altiscope.summarize.generate import GeneratedAccount, request_tokens
from altiscope.summarize.publication import Publication, PublicationState, assess


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _evidence(
    conn: psycopg.Connection, snapshot_id: int, ev: Evidence, ctx: PrContext
) -> dict[str, Any]:
    values: dict[str, Any] = dict(evidence_type=ev.type, quote=ev.quote, hunk_header=ev.hunk_header)
    row = None
    if ev.type in (EvidenceType.file, EvidenceType.hunk):
        row = conn.execute(
            "SELECT id FROM pr_files WHERE pull_request_id=%s AND path=%s AND included",
            (snapshot_id, ev.path),
        ).fetchone()
        key = "pr_file_id"
    elif ev.type == EvidenceType.review_comment:
        assert ev.comment_id is not None
        kind, github_id = ctx.comment_tokens[ev.comment_id]
        row = conn.execute(
            "SELECT id FROM pr_comments WHERE pull_request_id=%s AND kind=%s AND github_id=%s",
            (snapshot_id, kind, github_id),
        ).fetchone()
        key = "pr_comment_id"
    elif ev.type == EvidenceType.commit:
        assert ev.commit_sha is not None
        rows = conn.execute(
            "SELECT id FROM pr_commits WHERE pull_request_id=%s AND lower(sha) LIKE %s",
            (snapshot_id, ev.commit_sha.lower() + "%"),
        ).fetchall()
        row = rows[0] if len(rows) == 1 else None
        key = "pr_commit_id"
    else:
        return values
    if row is None:
        raise ValueError("Evidence does not belong to the stored snapshot")
    values[key] = int(row[0])
    return values


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
                schema=PrAccountOutput.model_json_schema(),
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
        checked = assess(generated.publication.output, ctx)
        published = checked.state == PublicationState.citation_valid
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
                narrative="",
                facts=Jsonb(ctx.facts.model_dump(mode="json")),
                input_manifest=Jsonb(ctx.manifest.model_dump(mode="json")),
            ),
        )
        if checked.output:
            for ordinal, claim in enumerate(checked.output.claims, 1):
                claim_id = insert(
                    conn,
                    "pr_claims",
                    dict(
                        pr_summary_id=summary_id, ordinal=ordinal, kind=claim.kind, text=claim.text
                    ),
                )
                for ev in claim.evidence:
                    insert(
                        conn,
                        "pr_claim_evidence",
                        dict(pr_claim_id=claim_id, **_evidence(conn, snapshot_id, ev, ctx)),
                    )
        return summary_id


def load_account(conn: psycopg.Connection, snapshot_id: int, ctx: PrContext) -> Publication:
    row = conn.execute(
        "SELECT id,status FROM pr_summaries WHERE pull_request_id=%s "
        "ORDER BY is_current DESC,id DESC LIMIT 1",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise ValueError("No account exists; run summarize first")
    if row[1] != "published":
        return assess(None, ctx)
    claims: list[dict[str, Any]] = []
    for claim_id, kind, text in conn.execute(
        "SELECT id,kind,text FROM pr_claims WHERE pr_summary_id=%s ORDER BY ordinal", (row[0],)
    ):
        evidence: list[dict[str, Any]] = []
        for ev in conn.execute(
            "SELECT e.evidence_type,e.quote,e.hunk_header,f.path,c.kind,c.github_id,m.sha "
            "FROM pr_claim_evidence e LEFT JOIN pr_files f ON f.id=e.pr_file_id "
            "LEFT JOIN pr_comments c ON c.id=e.pr_comment_id "
            "LEFT JOIN pr_commits m ON m.id=e.pr_commit_id WHERE e.pr_claim_id=%s ORDER BY e.id",
            (claim_id,),
        ):
            token = next(
                (t for t, identity in ctx.comment_tokens.items() if identity == (ev[4], ev[5])),
                None,
            )
            evidence.append(
                dict(
                    type=ev[0],
                    quote=ev[1],
                    hunk_header=ev[2],
                    path=ev[3],
                    comment_id=token,
                    commit_sha=ev[6],
                )
            )
        claims.append(dict(kind=kind, text=text, evidence=evidence))
    return assess(PrAccountOutput.model_validate(dict(claims=claims)), ctx)


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
    exclusions = {item.path: item.reason for item in manifest.excluded}
    decisions = [
        FileDecision(
            path=file.path,
            included=file.path in manifest.included_paths,
            reason=exclusions.get(file.path),
            additions=file.additions,
            deletions=file.deletions,
            patch_bytes=len((file.patch or "").encode()),
        )
        for file in snapshot.files
    ]
    return build_context(snapshot, PolicyOutcome(decisions), facts, manifest)
