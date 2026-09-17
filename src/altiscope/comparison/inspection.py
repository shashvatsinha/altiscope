"""Read-only inspection of one persisted comparison invocation."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

import psycopg
from psycopg import sql

from altiscope.assessment import render_assessment
from altiscope.review import render_frozen_source
from altiscope.store.comparisons import list_assessments, load_result, load_source
from altiscope.store.evaluation import load_review_record
from altiscope.store.recipes import load_recipe


def _money(value: Decimal | None, status: str) -> str:
    if status == "complete" and value is not None:
        return f"configured-price estimate ${value:.8f}"
    return "not incurred" if status == "not_incurred" else "unavailable"


def _duration(start: datetime | None, finish: datetime | None) -> str:
    if start is None or finish is None:
        return "unavailable"
    return f"{int((finish - start).total_seconds() * 1000)} ms"


def _calls(
    conn: psycopg.Connection, table: str, key: str, identity: UUID
) -> tuple[list[str], int, Decimal | None, str, int | None]:
    # table/key are fixed internal SQL fragments; no caller-controlled identifiers.
    rows = conn.execute(
        sql.SQL(
            "SELECT c.id,c.status,c.input_tokens,c.output_tokens,c.cache_read_tokens,"
            "c.cache_write_tokens,c.cost_usd,c.cost_status,c.latency_ms,c.provider,"
            "c.model_id,c.stop_reason,c.error,c.usage_status "
            "FROM {} x JOIN llm_calls c ON c.id=x.call_id WHERE x.{}=%s ORDER BY x.ordinal"
        ).format(sql.Identifier(table), sql.Identifier(key)),
        (identity,),
    ).fetchall()
    lines: list[str] = []
    cost = Decimal(0)
    cost_complete = True
    latency = 0
    latency_complete = True
    for ordinal, row in enumerate(rows, 1):
        usage = (
            ", ".join(
                f"{name}={value if value is not None else 'unavailable'}"
                for name, value in zip(
                    ("input", "output", "cache_read", "cache_write"), row[2:6], strict=True
                )
            )
            if row[13] == "measured"
            else "usage unavailable"
        )
        call_cost = Decimal(row[6]) if row[6] is not None else None
        if row[7] != "complete" or call_cost is None:
            cost_complete = False
        else:
            cost += call_cost
        if row[8] is None:
            latency_complete = False
        else:
            latency += int(row[8])
        lines.append(
            f"    attempt {ordinal} call {row[0]}: {row[1]}; {usage}; "
            f"cost {_money(call_cost, str(row[7]))}; latency "
            f"{str(row[8]) + ' ms' if row[8] is not None else 'unavailable'}; "
            f"{row[9]}/{row[10]}; stop {row[11] or 'unavailable'}"
            + (f"; error {row[12]}" if row[12] else "")
        )
    count = len(rows)
    cost_status = "not_incurred" if count == 0 else "complete" if cost_complete else "unavailable"
    return (
        lines,
        count,
        cost if count and cost_complete else None,
        cost_status,
        latency if count and latency_complete else None,
    )


def _review_lines(
    conn: psycopg.Connection, result_id: UUID, review_session_id: UUID | None
) -> tuple[list[str], set[str]]:
    rows = conn.execute(
        "SELECT id FROM review_sessions WHERE result_id=%s ORDER BY started_at,id", (result_id,)
    ).fetchall()
    lines = ["  Human reviews:"]
    if not rows:
        lines.append("    none recorded")
    exposed: set[str] = set()
    for row in rows:
        record = load_review_record(conn, UUID(str(row[0])))
        selected = review_session_id == UUID(str(row[0]))
        if selected:
            exposed = {
                str(item["assessment_id"])
                for item in cast(list[dict[str, object]], record["exposures"])
            }
        lines.append(
            f"    session {row[0]}: reviewer {record['reviewer_id']}; "
            f"role {record['reader_role']}; completed {record['completed_at'] or 'no'}; "
            f"prior exposure {record['declared_prior_assessment_exposure']}"
        )
        preparation = cast(dict[str, object] | None, record["preparation"])
        lines.append(
            "      preparation: "
            + (
                json.dumps(preparation["effort"], sort_keys=True)
                if preparation is not None
                else "unavailable (not recorded)"
            )
        )
        for revision in cast(list[dict[str, object]], record["revisions"]):
            if revision["kind"] != "initial_blind" and not selected:
                lines.append(
                    f"      revision {revision['revision_id']} ({revision['kind']}): "
                    "details available with its exposed review session"
                )
                continue
            correctness = cast(dict[str, object], revision["correctness"])
            usefulness = cast(dict[str, object], revision["usefulness"])
            lines.append(
                f"      revision {revision['revision_id']} ({revision['kind']}, "
                f"{revision['blind_status']}): correctness "
                f"{correctness['label'] or 'unavailable'}; "
                f"usefulness {usefulness['status']}"
                + (f" {usefulness['score']}/5" if usefulness["score"] is not None else "")
            )
            show_text = selected and (revision["kind"] == "initial_blind" or bool(exposed))
            if show_text and correctness["rationale"]:
                lines.append(f"        rationale: {correctness['rationale']}")
            if show_text and correctness["correction"]:
                lines.append(f"        correction: {correctness['correction']}")
            if show_text and usefulness["rationale"]:
                lines.append(f"        usefulness rationale: {usefulness['rationale']}")
            lines.append(f"        effort: {json.dumps(revision['effort'], sort_keys=True)}")
        if selected:
            for observation in cast(
                list[dict[str, object]], record["post_assessment_observations"]
            ):
                post_usefulness = cast(dict[str, object], observation["post_usefulness"])
                lines.append(
                    f"      assessment observation {observation['observation_id']}: "
                    f"assessment-related effort "
                    f"{json.dumps(observation['assessment_related_effort'], sort_keys=True)}; "
                    f"post usefulness {post_usefulness['status']}"
                    + (
                        f" {post_usefulness['score']}/5"
                        if post_usefulness["score"] is not None
                        else ""
                    )
                )
                lines.append(
                    f"        observation detail: {json.dumps(observation, sort_keys=True)}"
                )
    return lines, exposed


def render_comparison(  # noqa: PLR0912, PLR0915
    conn: psycopg.Connection,
    invocation_id: UUID,
    *,
    verbose: bool = False,
    review_session_id: UUID | None = None,
) -> str:
    """Render saved outcomes and accounting without executing or revealing an unexposed verdict."""
    invocation = conn.execute(
        "SELECT source_id,stage,experiment_scope,force_rerun,retention,status,"
        "started_at,completed_at,execution_build FROM comparison_invocations WHERE id=%s",
        (invocation_id,),
    ).fetchone()
    if invocation is None:
        raise ValueError("comparison invocation not found")
    source = load_source(conn, UUID(str(invocation[0])))
    if review_session_id is not None:
        review = conn.execute(
            "SELECT result_id FROM review_sessions WHERE id=%s", (review_session_id,)
        ).fetchone()
        if review is None:
            raise ValueError("review session not found")
        belongs = conn.execute(
            "SELECT 1 FROM comparison_members WHERE invocation_id=%s AND result_id=%s",
            (invocation_id, review[0]),
        ).fetchone()
        if belongs is None:
            raise ValueError("review session result is not in this invocation")
    member_rows = conn.execute(
        "SELECT id,ordinal,recipe_version_id,condition_label,disposition,result_id,"
        "current_call_count,current_cost_usd,current_cost_status "
        "FROM comparison_members WHERE invocation_id=%s ORDER BY ordinal",
        (invocation_id,),
    ).fetchall()
    lines = [
        f"Comparison invocation {invocation_id}: {invocation[5]}; "
        f"scope {invocation[2]}; stage {invocation[1]}; force rerun {invocation[3]}",
        f"Frozen source {source.id}: {source.kind}; content hash {source.content_hash}; "
        f"prepared text hash {source.prepared_text_hash}; repository ID {source.repository_id}",
        f"Altitude: {source.altitude or 'not applicable'}; query: "
        + (
            json.dumps(source.query, sort_keys=True)
            if source.query is not None
            else "not applicable"
        ),
    ]
    if source.kind == "pr":
        lines.append(
            f"Historical PR snapshot {source.pull_request_id}; "
            f"link {source.historical_pr_url or 'unavailable'}"
        )
    else:
        lines.append("Exact historical inputs:")
        for item in source.inputs:
            command = "show-report" if item.kind == "pr" else "show-aggregate"
            lines.append(
                f"  {item.kind} {item.report_version_id}; "
                f"altiscope {command} {item.report_version_id}; "
                f"source hash {item.source_hash or 'unavailable'}"
            )
            lines.extend(f"    PR {url}" for url in item.pr_urls)
    if verbose:
        lines.append(render_frozen_source(source).rstrip())
        lines.append(f"Execution build {invocation[8]}; retention {invocation[4]}")
    total_calls = 0
    total_repairs = 0
    total_assessment_calls = 0
    total_assessment_repairs = 0
    total_cost = Decimal(0)
    total_cost_complete = True
    for member in member_rows:
        member_id, ordinal, recipe_id, label, disposition, result_id = member[:6]
        recipe = load_recipe(conn, UUID(str(recipe_id)), require_executable=False)
        targets = conn.execute(
            "SELECT recipe_version_id FROM comparison_member_baseline_targets "
            "WHERE member_id=%s ORDER BY recipe_version_id",
            (member_id,),
        ).fetchall()
        lines.append(
            f"\n{ordinal}. {label}: {recipe.name} v{recipe.version} ({recipe.id}); "
            f"{disposition}; result {result_id or 'pending'}"
        )
        lines.append(
            f"  Recipe hash {recipe.configuration_hash}; prompt {recipe.prompt.version} "
            f"hash {recipe.prompt.content_hash}; model {recipe.config.provider.name}/"
            f"{recipe.config.model.wire_name} (underlying "
            f"{recipe.config.model.underlying_model_id or 'unavailable'}); "
            f"schema {recipe.config.output_contract.contract_id} "
            f"v{recipe.config.output_contract.version} ({recipe.schema_id})"
        )
        if targets:
            lines.append("  Baseline for: " + ", ".join(str(row[0]) for row in targets))
        if verbose:
            lines.append(
                "  Frozen recipe config: "
                + json.dumps(recipe.config.model_dump(mode="json"), sort_keys=True)
            )
            lines.append("  Exact prompt source:\n" + recipe.prompt.source_text)
        if result_id is None:
            lines.append("  Pending: no result or new spend recorded")
            continue
        result = load_result(conn, UUID(str(result_id)))
        origin = conn.execute(
            "SELECT origin_member_id,started_at,finished_at "
            "FROM comparison_run_results WHERE id=%s",
            (result.id,),
        ).fetchone()
        assert origin is not None
        call_lines, call_count, cost, cost_status, latency = _calls(
            conn, "comparison_result_calls", "result_id", result.id
        )
        lines.append(
            f"  Status {result.status}; origin result {result.id}; origin member {origin[0]}; "
            f"generation calls {call_count}; generation cost {_money(cost, cost_status)}; "
            f"model latency {str(latency) + ' ms' if latency is not None else 'unavailable'}; "
            f"generation elapsed {_duration(origin[1], origin[2])}"
        )
        if result.error_code:
            lines.append(f"  Failure {result.error_code}: {result.error_message or 'unavailable'}")
        else:
            lines.append(f"  Output hash {result.output_hash}; output:")
            lines.append(json.dumps(result.output, indent=2, sort_keys=True))
        current_cost = Decimal(member[7]) if member[7] is not None else None
        lines.append(
            f"  This invocation: {member[6]} new calls; "
            f"new cost {_money(current_cost, str(member[8]))}"
        )
        total_calls += int(member[6])
        if disposition == "generated":
            total_repairs += max(0, call_count - 1)
        if member[6]:
            if member[8] != "complete" or current_cost is None:
                total_cost_complete = False
            else:
                total_cost += current_cost
        lines.extend(call_lines)
        lines.append(f"  Repairs {max(0, call_count - 1)}; tree nodes not applicable (single step)")
        review_lines, exposed = _review_lines(
            conn, result.id, review_session_id if review_session_id is not None else None
        )
        lines.extend(review_lines)
        assessments = list_assessments(conn, target_result_id=result.id)
        lines.append("  Assessments: " + (str(len(assessments)) if assessments else "not run"))
        for assessment in assessments:
            assessor = load_recipe(
                conn, assessment.assessor_recipe_version_id, require_executable=False
            )
            assessment_times = conn.execute(
                "SELECT started_at,finished_at FROM comparison_assessments WHERE id=%s",
                (assessment.id,),
            ).fetchone()
            assert assessment_times is not None
            lines.append(
                "  " + render_assessment(assessment, reveal=str(assessment.id) in exposed).rstrip()
            )
            lines.append(
                f"    assessor {assessor.name} v{assessor.version} ({assessor.id}); "
                f"prompt {assessor.prompt.version} hash {assessor.prompt.content_hash}; "
                f"model {assessor.config.provider.name}/{assessor.config.model.wire_name}; "
                f"schema {assessor.config.output_contract.contract_id} "
                f"v{assessor.config.output_contract.version}"
            )
            (
                assessment_lines,
                assessment_calls,
                assessment_cost,
                assessment_status,
                assessment_latency,
            ) = _calls(conn, "comparison_assessment_calls", "assessment_id", assessment.id)
            lines.append(
                f"    assessment calls {assessment_calls}; cost "
                f"{_money(assessment_cost, assessment_status)}; model latency "
                + (f"{assessment_latency} ms" if assessment_latency is not None else "unavailable")
                + f"; elapsed {_duration(assessment_times[0], assessment_times[1])}"
            )
            lines.extend(assessment_lines)
            lines.append(f"    assessment repairs {max(0, assessment_calls - 1)}")
            total_assessment_calls += assessment_calls
            total_assessment_repairs += max(0, assessment_calls - 1)
        if assessments and review_session_id is None:
            lines.append(
                "  Reveal through `altiscope reviews reveal REVIEW_SESSION_ID ASSESSMENT_ID`."
            )
    status = (
        "complete"
        if total_calls and total_cost_complete
        else "unavailable"
        if total_calls
        else "not_incurred"
    )
    lines.append(
        f"\nCurrent invocation: {total_calls} new calls; new cost "
        f"{_money(total_cost if status == 'complete' else None, status)}; "
        f"elapsed {_duration(invocation[6], invocation[7])}; "
        f"generation repairs {total_repairs}; assessment calls {total_assessment_calls}; "
        f"assessment repairs {total_assessment_repairs}; tree nodes not applicable"
    )
    return "\n".join(lines) + "\n"
