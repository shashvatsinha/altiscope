"""Frozen sources, invocations, immutable results, reuse, and assessment records."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from altiscope.aggregate.generate import AggregateAttempt
from altiscope.aggregate.inputs import ReportInput
from altiscope.llm.execution import StructuredAttempt
from altiscope.store.aggregates import PostgresAggregateStore, load_pr_input
from altiscope.store.calls import save_recipe_calls
from altiscope.store.recipes import RecipeVersion, load_recipe
from altiscope.summarize.generate import Attempt

ResultStatus = Literal["succeeded", "preflight_failed", "invalid_output", "refused", "failed"]
ConditionLabel = Literal["candidate", "primary_baseline", "model_comparison"]
AssessmentStatus = Literal[
    "succeeded", "preflight_failed", "invalid_output", "refused", "failed", "inconclusive"
]
Attempts = tuple[Attempt, ...] | tuple[AggregateAttempt, ...] | tuple[StructuredAttempt, ...]
_ERROR_CODES = {
    "oversized_input",
    "budget_exceeded",
    "compatibility",
    "credentials",
    "truncation",
    "transport",
    "invalid_output",
    "refused",
    "independence_unknown",
    "same_underlying_model",
    "source_unavailable",
    "internal_error",
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _hash_json(value: object) -> str:
    return _hash_text(_canonical_json(value))


def _sanitized_error(code: str | None, message: str | None) -> tuple[str | None, str | None]:
    if code is None:
        return None, None
    safe_code = code if code in _ERROR_CODES else "internal_error"
    safe_message = re.sub(r"\s+", " ", message or "").strip()[:512]
    return safe_code, safe_message or None


@dataclass(frozen=True)
class ComparisonSource:
    id: UUID
    kind: Literal["pr", "aggregate"]
    stage: Literal["pr_summary", "aggregate"]
    repository_id: int
    pull_request_id: int | None
    preparation_document: dict[str, object]
    prepared_text: str
    content_hash: str
    prepared_text_hash: str
    query: dict[str, object] | None
    altitude: Literal["ic", "manager", "exec"] | None
    inputs: tuple[ReportInput, ...]
    historical_pr_url: str | None = None


@dataclass(frozen=True)
class InvocationMember:
    id: UUID
    ordinal: int
    recipe_version_id: UUID
    condition_label: ConditionLabel = "candidate"
    baseline_for_recipe_version_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class ComparisonInvocation:
    id: UUID
    source_id: UUID
    stage: Literal["pr_summary", "aggregate"]
    force_rerun: bool
    retention: Literal["full", "hashes_only"]
    members: tuple[InvocationMember, ...]


@dataclass(frozen=True)
class TerminalResult:
    status: ResultStatus
    started_at: datetime
    finished_at: datetime
    output: BaseModel | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class StoredResult:
    id: UUID
    source_id: UUID
    recipe_version_id: UUID
    status: ResultStatus
    output: dict[str, object] | None
    output_hash: str | None
    call_ids: tuple[int, ...]
    error_code: str | None = None
    error_message: str | None = None
    origin_retention: Literal["full", "hashes_only"] = "full"


@dataclass(frozen=True)
class TerminalAssessment:
    status: AssessmentStatus
    started_at: datetime
    finished_at: datetime
    input_document: dict[str, object]
    independence_evidence: dict[str, object]
    output_schema_version_id: UUID | None = None
    output: dict[str, object] | None = None
    verdict: Literal["agree", "disagree", "inconclusive"] | None = None
    rationale: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class StoredAssessment:
    id: UUID
    request_identity: UUID
    target_result_id: UUID
    assessor_recipe_version_id: UUID
    requesting_invocation_id: UUID | None
    requesting_member_id: UUID | None
    input_document: dict[str, object]
    input_hash: str
    independence_evidence: dict[str, object]
    status: AssessmentStatus
    verdict: Literal["agree", "disagree", "inconclusive"] | None
    rationale: str | None
    output: dict[str, object] | None
    output_hash: str | None
    call_ids: tuple[int, ...]
    error_code: str | None = None
    error_message: str | None = None


def freeze_pr_source(
    conn: psycopg.Connection,
    *,
    snapshot_id: int,
    preparation_document: dict[str, object],
    prepared_text: str,
    preparation_contract: dict[str, object],
    source_format_version: str = "pr-prepared-v1",
) -> ComparisonSource:
    """Freeze one exact PR snapshot and its already-computed preparation."""
    if not prepared_text.strip():
        raise ValueError("prepared source text must not be blank")
    if set(preparation_document) - {"facts", "manifest"}:
        raise ValueError("PR preparation must contain only curated facts and manifest")
    source_id = uuid4()
    with conn.transaction():
        row = conn.execute(
            "SELECT repository_id,normalized_snapshot,source_hash FROM pull_requests WHERE id=%s",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise ValueError("pull request snapshot not found")
        if row[1] is None or row[2] is None:
            raise ValueError("pull request snapshot lacks normalized source provenance")
        frozen = {
            "snapshot_id": snapshot_id,
            "snapshot": row[1],
            "snapshot_source_hash": str(row[2]),
            "preparation": preparation_document,
            "preparation_contract": preparation_contract,
            "prepared_text": prepared_text,
            "source_format_version": source_format_version,
        }
        content_hash = _hash_json(frozen)
        text_hash = _hash_text(prepared_text)
        conn.execute(
            "INSERT INTO comparison_sources"
            "(id,kind,stage,repository_id,pull_request_id,source_format_version,"
            "preparation_contract,preparation_document,prepared_text,content_hash,"
            "prepared_text_hash,experiment_scope) "
            "VALUES(%s,'pr','pr_summary',%s,%s,%s,%s,%s,%s,%s,%s,'single_step')",
            (
                source_id,
                int(row[0]),
                snapshot_id,
                source_format_version,
                Jsonb(preparation_contract),
                Jsonb(preparation_document),
                prepared_text,
                content_hash,
                text_hash,
            ),
        )
    return ComparisonSource(
        source_id,
        "pr",
        "pr_summary",
        int(row[0]),
        snapshot_id,
        preparation_document,
        prepared_text,
        content_hash,
        text_hash,
        None,
        None,
        (),
        str(row[1]["html_url"]) if row[1].get("html_url") else None,
    )


def _input_repository_ids(conn: psycopg.Connection, supplied: ReportInput) -> set[int]:
    if supplied.kind == "pr":
        rows = conn.execute(
            "SELECT p.repository_id FROM pr_summaries s "
            "JOIN pull_requests p ON p.id=s.pull_request_id WHERE s.id=%s",
            (int(supplied.report_version_id),),
        ).fetchall()
    else:
        rows = conn.execute(
            "WITH RECURSIVE reports(id) AS ("
            " SELECT %s::uuid UNION SELECT i.child_report_id FROM aggregate_report_inputs i "
            " JOIN reports r ON i.report_id=r.id WHERE i.child_report_id IS NOT NULL"
            ") SELECT DISTINCT p.repository_id FROM reports r "
            "JOIN aggregate_report_inputs i ON i.report_id=r.id "
            "JOIN pr_summaries s ON s.id=i.pr_summary_id "
            "JOIN pull_requests p ON p.id=s.pull_request_id",
            (UUID(supplied.report_version_id),),
        ).fetchall()
    return {int(row[0]) for row in rows}


def freeze_aggregate_source(
    conn: psycopg.Connection,
    *,
    repository_id: int,
    inputs: tuple[ReportInput, ...],
    query: dict[str, object],
    altitude: Literal["ic", "manager", "exec"],
    prepared_text: str,
    preparation_contract: dict[str, object],
    source_format_version: str = "aggregate-single-step-v1",
) -> ComparisonSource:
    """Freeze an ordered, exact set of saved reports for one composition step."""
    if not inputs:
        raise ValueError("aggregate comparison source requires at least one input report")
    if not prepared_text.strip():
        raise ValueError("prepared source text must not be blank")
    identities = [(item.kind, item.report_version_id) for item in inputs]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate aggregate source input")
    source_id = uuid4()
    documents: list[dict[str, object]] = []
    with conn.transaction():
        repository = conn.execute(
            "SELECT 1 FROM repositories WHERE id=%s", (repository_id,)
        ).fetchone()
        if repository is None:
            raise ValueError("repository not found")
        for item in inputs:
            expected = (
                load_pr_input(conn, int(item.report_version_id))
                if item.kind == "pr"
                else PostgresAggregateStore(conn).get(item.report_version_id).as_input()
            )
            if expected != item:
                raise ValueError("aggregate input does not match stored report version")
            if _input_repository_ids(conn, item) != {repository_id}:
                raise ValueError("aggregate input does not belong to the source repository")
            documents.append(
                {
                    "kind": item.kind,
                    "report_version_id": item.report_version_id,
                    "text": item.text,
                    "source_hash": item.source_hash,
                    "pr_urls": list(item.pr_urls),
                }
            )
        preparation_document: dict[str, object] = {
            "inputs": documents,
            "query": query,
            "altitude": altitude,
            "experiment_scope": "single_step",
        }
        frozen = {
            "repository_id": repository_id,
            "preparation": preparation_document,
            "preparation_contract": preparation_contract,
            "prepared_text": prepared_text,
            "source_format_version": source_format_version,
        }
        content_hash = _hash_json(frozen)
        text_hash = _hash_text(prepared_text)
        conn.execute(
            "INSERT INTO comparison_sources"
            "(id,kind,stage,repository_id,source_format_version,preparation_contract,"
            "preparation_document,prepared_text,content_hash,prepared_text_hash,query,altitude,"
            "experiment_scope) VALUES(%s,'aggregate','aggregate',%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "'single_step')",
            (
                source_id,
                repository_id,
                source_format_version,
                Jsonb(preparation_contract),
                Jsonb(preparation_document),
                prepared_text,
                content_hash,
                text_hash,
                Jsonb(query),
                altitude,
            ),
        )
        for ordinal, item in enumerate(inputs, 1):
            conn.execute(
                "INSERT INTO comparison_source_inputs"
                "(source_id,ordinal,pr_summary_id,aggregate_report_id,input_kind,rendered_text,"
                "rendered_text_hash,source_hash,pr_urls) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    source_id,
                    ordinal,
                    int(item.report_version_id) if item.kind == "pr" else None,
                    UUID(item.report_version_id) if item.kind == "aggregate" else None,
                    "pr_summary" if item.kind == "pr" else "aggregate_report",
                    item.text,
                    _hash_text(item.text),
                    item.source_hash or _hash_text(item.text),
                    list(item.pr_urls),
                ),
            )
    return ComparisonSource(
        source_id,
        "aggregate",
        "aggregate",
        repository_id,
        None,
        preparation_document,
        prepared_text,
        content_hash,
        text_hash,
        query,
        altitude,
        inputs,
    )


def load_source(conn: psycopg.Connection, source_id: UUID | str) -> ComparisonSource:
    row = conn.execute(
        "SELECT id,kind,stage,repository_id,pull_request_id,preparation_document,prepared_text,"
        "content_hash,prepared_text_hash,query,altitude FROM comparison_sources WHERE id=%s",
        (UUID(str(source_id)),),
    ).fetchone()
    if row is None:
        raise ValueError("comparison source not found")
    input_rows = conn.execute(
        "SELECT input_kind,pr_summary_id,aggregate_report_id,rendered_text,source_hash,pr_urls "
        "FROM comparison_source_inputs WHERE source_id=%s ORDER BY ordinal",
        (UUID(str(source_id)),),
    ).fetchall()
    inputs = tuple(
        ReportInput(
            "pr" if item[0] == "pr_summary" else "aggregate",
            str(item[1] if item[1] is not None else item[2]),
            str(item[3]),
            tuple(str(url) for url in item[5]),
            str(item[4]),
        )
        for item in input_rows
    )
    preparation_document = cast(dict[str, object], row[5])
    historical_pr_url: str | None = None
    if row[1] == "pr":
        # Older review workflow rows included a raw snapshot in this JSON. The
        # immutable pull_requests row owns it; keep it out of review/assessment data.
        preparation_document = {
            key: value
            for key, value in preparation_document.items()
            if key not in ("snapshot", "snapshot_source_hash")
        }
        snapshot_row = conn.execute(
            "SELECT normalized_snapshot FROM pull_requests WHERE id=%s", (row[4],)
        ).fetchone()
        if snapshot_row is not None:
            historical_pr_url = snapshot_row[0].get("html_url")
    return ComparisonSource(
        UUID(str(row[0])),
        row[1],
        row[2],
        int(row[3]),
        int(row[4]) if row[4] is not None else None,
        preparation_document,
        str(row[6]),
        str(row[7]),
        str(row[8]),
        row[9],
        row[10],
        inputs,
        historical_pr_url,
    )


def create_invocation(
    conn: psycopg.Connection,
    *,
    source_id: UUID,
    recipe_version_ids: tuple[UUID, ...],
    force_rerun: bool,
    retention: Literal["full", "hashes_only"],
    execution_build: str,
    protocol_artifact_id: UUID | None = None,
    condition_labels: dict[UUID, ConditionLabel] | None = None,
    baseline_targets: dict[UUID, tuple[UUID, ...]] | None = None,
) -> ComparisonInvocation:
    if len(recipe_version_ids) < 2 or len(set(recipe_version_ids)) != len(recipe_version_ids):
        raise ValueError("a comparison requires at least two distinct recipe versions")
    if retention not in ("full", "hashes_only"):
        raise ValueError("unknown payload retention policy")
    invocation_id = uuid4()
    members: list[InvocationMember] = []
    labels = condition_labels or {}
    targets = baseline_targets or {}
    unknown_metadata = (set(labels) | set(targets)) - set(recipe_version_ids)
    if unknown_metadata:
        raise ValueError("comparison member metadata names a recipe outside the invocation")
    allowed_targets = set(recipe_version_ids)
    if any(set(values) - allowed_targets for values in targets.values()):
        raise ValueError("baseline metadata targets a recipe outside the invocation")
    with conn.transaction():
        source = load_source(conn, source_id)
        recipes = [load_recipe(conn, recipe_id) for recipe_id in recipe_version_ids]
        if any(recipe.stage != source.stage for recipe in recipes):
            raise ValueError("all recipes must match the frozen source stage")
        specification = {
            "source_id": str(source_id),
            "recipe_version_ids": [str(value) for value in recipe_version_ids],
            "force_rerun": force_rerun,
            "retention": retention,
            "experiment_scope": "single_step",
            "execution_build": execution_build,
            "members": [
                {
                    "recipe_version_id": str(recipe_id),
                    "condition_label": labels.get(recipe_id, "candidate"),
                    "baseline_for_recipe_version_ids": [
                        str(value) for value in targets.get(recipe_id, ())
                    ],
                }
                for recipe_id in recipe_version_ids
            ],
        }
        conn.execute(
            "INSERT INTO comparison_invocations"
            "(id,source_id,stage,experiment_scope,force_rerun,retention,protocol_artifact_id,"
            "execution_build,specification) VALUES(%s,%s,%s,'single_step',%s,%s,%s,%s,%s)",
            (
                invocation_id,
                source_id,
                source.stage,
                force_rerun,
                retention,
                protocol_artifact_id,
                execution_build,
                Jsonb(specification),
            ),
        )
        for ordinal, recipe_id in enumerate(recipe_version_ids, 1):
            label = labels.get(recipe_id, "candidate")
            baseline_for = targets.get(recipe_id, ())
            member = InvocationMember(uuid4(), ordinal, recipe_id, label, baseline_for)
            conn.execute(
                "INSERT INTO comparison_members"
                "(id,invocation_id,ordinal,recipe_version_id,condition_label) "
                "VALUES(%s,%s,%s,%s,%s)",
                (member.id, invocation_id, ordinal, recipe_id, label),
            )
            for target in baseline_for:
                conn.execute(
                    "INSERT INTO comparison_member_baseline_targets"
                    "(member_id,recipe_version_id) VALUES(%s,%s)",
                    (member.id, target),
                )
            members.append(member)
    return ComparisonInvocation(
        invocation_id, source_id, source.stage, force_rerun, retention, tuple(members)
    )


def complete_invocation(conn: psycopg.Connection, invocation_id: UUID) -> None:
    """Finalize an invocation only after every frozen member has an outcome."""
    with conn.transaction():
        row = conn.execute(
            "SELECT status FROM comparison_invocations WHERE id=%s FOR UPDATE",
            (invocation_id,),
        ).fetchone()
        if row is None:
            raise ValueError("comparison invocation not found")
        if row[0] != "running":
            raise ValueError("comparison invocation is already finalized")
        pending = conn.execute(
            "SELECT count(*) FROM comparison_members "
            "WHERE invocation_id=%s AND disposition='pending'",
            (invocation_id,),
        ).fetchone()
        assert pending is not None
        status = "completed" if int(pending[0]) == 0 else "incomplete"
        conn.execute(
            "UPDATE comparison_invocations SET status=%s,completed_at=clock_timestamp() "
            "WHERE id=%s",
            (status, invocation_id),
        )


def comparison_cache_key(source: ComparisonSource, recipe: RecipeVersion) -> str:
    return _hash_json(
        {
            "namespace": "comparison",
            "version": 1,
            "source_id": str(source.id),
            "source_hash": source.content_hash,
            "stage": source.stage,
            "scope": "single_step",
            "recipe_version_id": str(recipe.id),
            "recipe_configuration_hash": recipe.configuration_hash,
            "execution_contract": recipe.config.interpretation.model_dump(mode="json"),
        }
    )


def find_comparison_result(
    conn: psycopg.Connection, *, source_id: UUID, recipe_version_id: UUID
) -> StoredResult | None:
    source = load_source(conn, source_id)
    recipe = load_recipe(conn, recipe_version_id)
    key = comparison_cache_key(source, recipe)
    row = conn.execute(
        "SELECT id FROM comparison_run_results WHERE cache_key=%s AND status='succeeded' "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (key,),
    ).fetchone()
    return load_result(conn, UUID(str(row[0]))) if row else None


def _member_context(conn: psycopg.Connection, member_id: UUID) -> tuple[UUID, UUID, UUID, str, str]:
    row = conn.execute(
        "SELECT m.invocation_id,m.recipe_version_id,i.source_id,i.retention,m.disposition "
        "FROM comparison_members m JOIN comparison_invocations i ON i.id=m.invocation_id "
        "WHERE m.id=%s FOR UPDATE",
        (member_id,),
    ).fetchone()
    if row is None:
        raise ValueError("comparison member not found")
    return UUID(str(row[0])), UUID(str(row[1])), UUID(str(row[2])), str(row[3]), str(row[4])


def save_result(
    conn: psycopg.Connection,
    *,
    member_id: UUID,
    terminal: TerminalResult,
    attempts: Attempts,
) -> StoredResult:
    """Atomically save a terminal result, every real call, and member finalization."""
    if terminal.finished_at < terminal.started_at:
        raise ValueError("result finish time precedes start time")
    if terminal.status == "succeeded":
        if terminal.output is None or terminal.error_code is not None or not attempts:
            raise ValueError("successful generated results require output and at least one attempt")
    elif terminal.output is not None or not terminal.error_code:
        raise ValueError("failed results require an error code and no usable output")
    result_id = uuid4()
    error_code, error_message = _sanitized_error(terminal.error_code, terminal.error_message)
    with conn.transaction():
        _, recipe_id, source_id, retention, disposition = _member_context(conn, member_id)
        if disposition != "pending":
            raise ValueError("comparison member is already finalized")
        source = load_source(conn, source_id)
        recipe = load_recipe(conn, recipe_id)
        if source.stage != recipe.stage:
            raise ValueError("member recipe and source stages do not match")
        output_document = terminal.output.model_dump(mode="json") if terminal.output else None
        if terminal.output is not None:
            validated = recipe.output_type.model_validate(output_document)
            output_document = validated.model_dump(mode="json")
        output_hash = _hash_json(output_document) if output_document is not None else None
        conn.execute(
            "INSERT INTO comparison_run_results"
            "(id,origin_member_id,source_id,recipe_version_id,output_schema_version_id,"
            "cache_namespace,cache_key_version,cache_key,status,output_document,output_hash,"
            "error_code,error_message,started_at,finished_at) "
            "VALUES(%s,%s,%s,%s,%s,'comparison',1,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                result_id,
                member_id,
                source_id,
                recipe_id,
                recipe.schema_id,
                comparison_cache_key(source, recipe),
                terminal.status,
                Jsonb(output_document) if output_document is not None else None,
                output_hash,
                error_code,
                error_message,
                terminal.started_at,
                terminal.finished_at,
            ),
        )
        call_ids = save_recipe_calls(
            conn,
            attempts=attempts,
            recipe=recipe,
            retention=retention,
            snapshot_id=source.pull_request_id,
        )
        for ordinal, call_id in enumerate(call_ids, 1):
            conn.execute(
                "INSERT INTO comparison_result_calls(result_id,ordinal,call_id) VALUES(%s,%s,%s)",
                (result_id, ordinal, call_id),
            )
            conn.execute(
                "INSERT INTO llm_call_owners(call_id,owner_kind,result_id,ordinal) "
                "VALUES(%s,'comparison_result',%s,%s)",
                (call_id, result_id, ordinal),
            )
        totals = (
            conn.execute(
                "SELECT COALESCE(sum(cost_usd),0),bool_and(cost_status='complete') "
                "FROM llm_calls WHERE id=ANY(%s)",
                (list(call_ids),),
            ).fetchone()
            if call_ids
            else None
        )
        if totals is None:
            total_cost = None
            cost_status = "not_incurred"
        else:
            cost_status = "complete" if totals[1] else "unavailable"
            total_cost = totals[0] if totals[1] else None
        conn.execute(
            "UPDATE comparison_members SET disposition='generated',result_id=%s,"
            "current_call_count=%s,current_cost_usd=%s,current_cost_status=%s,"
            "finalized_at=clock_timestamp() WHERE id=%s",
            (result_id, len(call_ids), total_cost, cost_status, member_id),
        )
    return StoredResult(
        result_id,
        source_id,
        recipe_id,
        terminal.status,
        output_document,
        output_hash,
        call_ids,
        error_code,
        error_message,
        retention,  # type: ignore[arg-type]
    )


def reuse_result(conn: psycopg.Connection, *, member_id: UUID, result_id: UUID) -> StoredResult:
    with conn.transaction():
        _, recipe_id, source_id, _, disposition = _member_context(conn, member_id)
        if disposition != "pending":
            raise ValueError("comparison member is already finalized")
        result = load_result(conn, result_id)
        if result.status != "succeeded":
            raise ValueError("only successful comparison results can be reused")
        if result.source_id != source_id or result.recipe_version_id != recipe_id:
            raise ValueError("cached result does not match member source and recipe")
        conn.execute(
            "UPDATE comparison_members SET disposition='reused',result_id=%s,"
            "current_call_count=0,current_cost_usd=NULL,current_cost_status='not_incurred',"
            "finalized_at=clock_timestamp() WHERE id=%s",
            (result_id, member_id),
        )
    return result


def load_result(conn: psycopg.Connection, result_id: UUID | str) -> StoredResult:
    row = conn.execute(
        "SELECT r.id,r.source_id,r.recipe_version_id,r.status,r.output_document,r.output_hash,"
        "r.error_code,r.error_message,i.retention FROM comparison_run_results r "
        "JOIN comparison_members m ON m.id=r.origin_member_id "
        "JOIN comparison_invocations i ON i.id=m.invocation_id WHERE r.id=%s",
        (UUID(str(result_id)),),
    ).fetchone()
    if row is None:
        raise ValueError("comparison result not found")
    calls = conn.execute(
        "SELECT call_id FROM comparison_result_calls WHERE result_id=%s ORDER BY ordinal",
        (UUID(str(result_id)),),
    ).fetchall()
    return StoredResult(
        UUID(str(row[0])),
        UUID(str(row[1])),
        UUID(str(row[2])),
        row[3],
        row[4],
        str(row[5]) if row[5] is not None else None,
        tuple(int(call[0]) for call in calls),
        str(row[6]) if row[6] is not None else None,
        str(row[7]) if row[7] is not None else None,
        row[8],
    )


def save_assessment(
    conn: psycopg.Connection,
    *,
    target_result_id: UUID,
    assessor_recipe_version_id: UUID,
    terminal: TerminalAssessment,
    attempts: Attempts,
    retention: Literal["full", "hashes_only"],
    requesting_invocation_id: UUID | None = None,
    requesting_member_id: UUID | None = None,
) -> StoredAssessment:
    """Save an assessment separately from the generated result it evaluates."""
    if terminal.finished_at < terminal.started_at:
        raise ValueError("assessment finish time precedes start time")
    succeeded = terminal.status in ("succeeded", "inconclusive")
    if succeeded:
        if (
            terminal.output is None
            or terminal.verdict is None
            or not terminal.rationale
            or terminal.output_schema_version_id is None
            or terminal.error_code is not None
        ):
            raise ValueError("completed assessments require output, verdict, rationale, and schema")
        if terminal.status == "inconclusive" and terminal.verdict != "inconclusive":
            raise ValueError("inconclusive assessment status requires an inconclusive verdict")
        if terminal.status == "succeeded" and terminal.verdict == "inconclusive":
            raise ValueError("an inconclusive verdict requires inconclusive assessment status")
    elif terminal.output is not None or terminal.verdict is not None or not terminal.error_code:
        raise ValueError("failed assessments require an error code and no verdict/output")
    assessment_id = uuid4()
    request_identity = uuid4()
    error_code, error_message = _sanitized_error(terminal.error_code, terminal.error_message)
    with conn.transaction():
        target = load_result(conn, target_result_id)
        if target.status != "succeeded":
            raise ValueError("assessments require a successful exact result")
        validate_assessment_request_context(
            conn,
            target_result_id=target_result_id,
            requesting_invocation_id=requesting_invocation_id,
            requesting_member_id=requesting_member_id,
        )
        recipe = load_recipe(conn, assessor_recipe_version_id)
        if recipe.stage != "verify":
            raise ValueError("assessor recipe must use the verify stage")
        output_document = terminal.output
        if output_document is not None:
            output_document = recipe.output_type.model_validate(output_document).model_dump(
                mode="json"
            )
        output_hash = _hash_json(output_document) if output_document is not None else None
        conn.execute(
            "INSERT INTO comparison_assessments"
            "(id,target_result_id,assessor_recipe_version_id,requesting_invocation_id,"
            "requesting_member_id,request_identity,input_document,input_hash,"
            "independence_evidence,status,verdict,rationale,output_schema_version_id,"
            "output_document,output_hash,error_code,error_message,started_at,finished_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                assessment_id,
                target_result_id,
                assessor_recipe_version_id,
                requesting_invocation_id,
                requesting_member_id,
                request_identity,
                Jsonb(terminal.input_document),
                _hash_json(terminal.input_document),
                Jsonb(terminal.independence_evidence),
                terminal.status,
                terminal.verdict,
                terminal.rationale,
                terminal.output_schema_version_id,
                Jsonb(output_document) if output_document is not None else None,
                output_hash,
                error_code,
                error_message,
                terminal.started_at,
                terminal.finished_at,
            ),
        )
        call_ids = save_recipe_calls(conn, attempts=attempts, recipe=recipe, retention=retention)
        for ordinal, call_id in enumerate(call_ids, 1):
            conn.execute(
                "INSERT INTO comparison_assessment_calls(assessment_id,ordinal,call_id) "
                "VALUES(%s,%s,%s)",
                (assessment_id, ordinal, call_id),
            )
            conn.execute(
                "INSERT INTO llm_call_owners(call_id,owner_kind,assessment_id,ordinal) "
                "VALUES(%s,'assessment',%s,%s)",
                (call_id, assessment_id, ordinal),
            )
    return load_assessment(conn, assessment_id)


def validate_assessment_request_context(
    conn: psycopg.Connection,
    *,
    target_result_id: UUID,
    requesting_invocation_id: UUID | None,
    requesting_member_id: UUID | None,
) -> None:
    """Require any comparison attribution to contain the exact target result."""
    if requesting_invocation_id is not None:
        invocation_target = conn.execute(
            "SELECT 1 FROM comparison_members WHERE invocation_id=%s AND result_id=%s",
            (requesting_invocation_id, target_result_id),
        ).fetchone()
        if invocation_target is None:
            raise ValueError("requesting assessment invocation does not contain the target result")
    if requesting_member_id is not None:
        member_target = conn.execute(
            "SELECT 1 FROM comparison_members WHERE id=%s AND invocation_id=%s AND result_id=%s",
            (requesting_member_id, requesting_invocation_id, target_result_id),
        ).fetchone()
        if member_target is None:
            raise ValueError(
                "requesting assessment member must belong to the supplied invocation "
                "and target its exact result"
            )


def load_assessment(conn: psycopg.Connection, assessment_id: UUID | str) -> StoredAssessment:
    """Load one exact assessment, including its retained verdict and ordered real calls."""
    row = conn.execute(
        "SELECT id,request_identity,target_result_id,assessor_recipe_version_id,"
        "requesting_invocation_id,requesting_member_id,input_document,input_hash,"
        "independence_evidence,status,verdict,rationale,output_document,output_hash,"
        "error_code,error_message FROM comparison_assessments WHERE id=%s",
        (UUID(str(assessment_id)),),
    ).fetchone()
    if row is None:
        raise ValueError("assessment not found")
    calls = conn.execute(
        "SELECT call_id FROM comparison_assessment_calls WHERE assessment_id=%s ORDER BY ordinal",
        (UUID(str(assessment_id)),),
    ).fetchall()
    return StoredAssessment(
        id=UUID(str(row[0])),
        request_identity=UUID(str(row[1])),
        target_result_id=UUID(str(row[2])),
        assessor_recipe_version_id=UUID(str(row[3])),
        requesting_invocation_id=UUID(str(row[4])) if row[4] is not None else None,
        requesting_member_id=UUID(str(row[5])) if row[5] is not None else None,
        input_document=row[6],
        input_hash=str(row[7]),
        independence_evidence=row[8],
        status=row[9],
        verdict=row[10],
        rationale=str(row[11]) if row[11] is not None else None,
        output=row[12],
        output_hash=str(row[13]) if row[13] is not None else None,
        call_ids=tuple(int(call[0]) for call in calls),
        error_code=str(row[14]) if row[14] is not None else None,
        error_message=str(row[15]) if row[15] is not None else None,
    )


def list_assessments(
    conn: psycopg.Connection, *, target_result_id: UUID
) -> tuple[StoredAssessment, ...]:
    """Return immutable assessment history; absence represents the not-run state."""
    rows = conn.execute(
        "SELECT id FROM comparison_assessments WHERE target_result_id=%s ORDER BY created_at,id",
        (target_result_id,),
    ).fetchall()
    return tuple(load_assessment(conn, UUID(str(row[0]))) for row in rows)
