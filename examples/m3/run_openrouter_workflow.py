"""Resume the bounded M3 live workflow one stage at a time.

Dry run is the default. --execute makes paid OpenRouter calls. Progress is saved
after each case so a failed process does not hide completed results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from altiscope.assessment import run_assessment
from altiscope.comparison.service import plan_recipes, run_comparison
from altiscope.config import load_settings
from altiscope.llm.registry import Registry
from altiscope.llm.tokens import estimate_tokens
from altiscope.prompts import load_prompt
from altiscope.store.comparisons import list_assessments, load_result, load_source
from altiscope.store.db import connect
from altiscope.store.recipes import RecipeVersion, load_recipe
from altiscope.store.snapshots import load_snapshot
from altiscope.summarize.service import summarize

INVENTORY_PATH = Path("docs/evaluation/m3-workflow-sources-v1.json")
PROGRESS_PATH = Path("docs/evaluation/m3-workflow-progress.json")
SPEC_PATH = Path("docs/evaluation/m3-workflow-run-spec-v1.json")
PR_RECIPES = (
    UUID("3c846144-d947-422a-83eb-c2570eeb3df8"),
    UUID("81841177-eb34-4ae7-b4c2-3ab8e2d8408c"),
)
AGGREGATE_RECIPES = (
    UUID("b39518cd-7cd7-4045-8fcf-fa98cb9d0c46"),
    UUID("b6b568f4-98fd-4a65-b9b0-c2e82c9f17d7"),
)
ASSESSOR = UUID("cd012661-0d58-4d44-bb11-2d406ec26b04")
HELD_OUT_ORDER = (1259, 1256, 1241, 1253, 1249, 1245, 1201, 1260)
SCOPES = {
    "all20": lambda cases: cases,
    "heldout8": lambda cases: [item for item in cases if item["group"] == "held_out"],
}


def _save(progress: dict[str, Any], path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _load_progress(path: Path, inventory_hash: str) -> dict[str, Any]:
    if path.exists():
        progress: dict[str, Any] = json.loads(path.read_text())
        if progress.get("source_inventory_sha256") != inventory_hash:
            raise ValueError("progress belongs to a different frozen source inventory")
        return progress
    return {
        "kind": "m3-openrouter-workflow-progress-v1",
        "source_inventory_sha256": inventory_hash,
        "pr": {},
        "upstream": {},
        "aggregate": {},
        "assessment": {},
    }


def _spent(conn: psycopg.Connection) -> Decimal:
    row = conn.execute(
        "SELECT COALESCE(sum(cost_usd),0),"
        "count(*) FILTER (WHERE cost_status IS DISTINCT FROM 'complete') "
        "FROM llm_calls WHERE provider='openrouter'"
    ).fetchone()
    assert row is not None
    if int(row[1]) > 0:
        raise ValueError("OpenRouter call cost is unavailable; stop for manual spend review")
    return Decimal(row[0])


def _ceiling(recipe: RecipeVersion, input_tokens: int) -> Decimal:
    pricing = recipe.config.pricing
    if pricing.status != "configured_estimate":
        raise ValueError(f"recipe {recipe.id} has no configured price")
    # Pad source/prompt estimates for schema, JSON wrapping, and repair text.
    padded_input = input_tokens + estimate_tokens(recipe.prompt.body) + 5_000
    calls = 1 + recipe.config.budget.repair_limit
    estimate = (
        (
            Decimal(padded_input) * Decimal(str(pricing.input_usd_per_mtok))
            + Decimal(recipe.config.generation.reserved_output_tokens)
            * Decimal(str(pricing.output_usd_per_mtok))
        )
        * Decimal(calls)
        / Decimal(1_000_000)
    )
    return estimate


def _require_room(conn: psycopg.Connection, cap: Decimal, ceiling: Decimal) -> None:
    spent = _spent(conn)
    if spent + ceiling > cap:
        raise ValueError(
            f"spend gate: recorded ${spent:.4f} + next-case ceiling ${ceiling:.4f} "
            f"exceeds approved ${cap:.2f}"
        )


def _comparison_record(run: Any) -> dict[str, object]:
    return {
        "invocation_id": str(run.invocation.id),
        "elapsed_ms": run.elapsed_ms,
        "new_call_count": run.new_call_count,
        "new_cost_status": run.new_cost_status,
        "new_estimated_cost_usd": (
            str(run.new_estimated_cost_usd) if run.new_estimated_cost_usd is not None else None
        ),
        "members": [
            {
                "member_id": str(member.member_id),
                "recipe_id": str(member.recipe.id),
                "condition": member.condition_label,
                "result_id": str(member.result.id),
                "status": member.result.status,
                "disposition": member.disposition,
                "new_call_count": member.current.call_count,
                "model_latency_ms": member.current.model_latency_ms,
                "new_cost_status": member.current.cost_status,
                "new_cost_usd": (
                    str(member.current.estimated_cost_usd)
                    if member.current.estimated_cost_usd is not None
                    else None
                ),
            }
            for member in run.members
        ],
    }


def _upstream_record(
    conn: psycopg.Connection, report_id: int, snapshot_id: int
) -> dict[str, object]:
    row = conn.execute(
        "SELECT s.status,c.generation_id FROM pr_summaries s "
        "JOIN llm_calls c ON c.id=s.llm_call_id WHERE s.id=%s",
        (report_id,),
    ).fetchone()
    assert row is not None
    calls = conn.execute(
        "SELECT count(*),sum(cost_usd),bool_and(cost_status='complete'),sum(latency_ms) "
        "FROM llm_calls WHERE generation_id=%s",
        (row[1],),
    ).fetchone()
    assert calls is not None
    complete = bool(calls[2])
    return {
        "report_id": report_id,
        "snapshot_id": snapshot_id,
        "status": str(row[0]),
        "generation_id": str(row[1]),
        "call_count": int(calls[0]),
        "cost_status": "complete" if complete else "unavailable",
        "estimated_cost_usd": str(calls[1]) if complete and calls[1] is not None else None,
        "model_latency_ms": int(calls[3]) if calls[3] is not None else None,
    }


def _pr_stage(
    conn: psycopg.Connection,
    *,
    cases: list[dict[str, Any]],
    progress: dict[str, Any],
    path: Path,
    cap: Decimal,
) -> None:
    records: dict[str, Any] = progress["pr"]
    for case in cases:
        case_id = str(case["case_id"])
        if case_id in records:
            continue
        source_id = UUID(str(case["source_id"]))
        source = load_source(conn, source_id)
        if source.pull_request_id != int(case["snapshot_id"]):
            raise ValueError(f"{case_id}: frozen snapshot ID changed")
        planned = plan_recipes(conn, PR_RECIPES, include_primary_baselines=True)
        ceiling = sum(
            (_ceiling(item.recipe, int(case["estimated_prepared_tokens"])) for item in planned),
            Decimal(0),
        )
        _require_room(conn, cap, ceiling)
        run = run_comparison(
            conn,
            source_id=source_id,
            recipe_version_ids=PR_RECIPES,
            retention="full",
            execution_build="m3-workflow-v1",
        )
        conn.commit()
        records[case_id] = {"source_id": str(source_id), **_comparison_record(run)}
        _save(progress, path)
        print(f"{case_id}: {run.invocation.id}; spent ${_spent(conn):.4f}", flush=True)


def _upstream_stage(
    conn: psycopg.Connection,
    *,
    cases: list[dict[str, Any]],
    progress: dict[str, Any],
    path: Path,
    cap: Decimal,
) -> None:
    records: dict[str, Any] = progress["upstream"]
    by_number = {int(item["pr_number"]): item for item in cases}
    settings = load_settings()
    registry = Registry.load(settings.prompts_dir.parent / "config/models.yaml")
    prompt = load_prompt(settings.prompts_dir / "pr_summary/v3.md")
    if prompt.content_hash != "429bdbfdd2fae2c20933fc7a2796872a1cc3746086ab51d71611cf3accb7fb56":
        raise ValueError("upstream PR prompt changed after demo preparation")
    if registry.stages["pr_summary"].candidates[0] != "openrouter-anthropic":
        raise ValueError("upstream PR model route changed after demo preparation")
    model = registry.models[registry.stages["pr_summary"].candidates[0]]
    input_rate = Decimal(str(model.input_usd_per_mtok))
    output_rate = Decimal(str(model.output_usd_per_mtok))
    for number in HELD_OUT_ORDER:
        if str(number) in records:
            continue
        case = by_number[number]
        stored = load_snapshot(conn, "microsoft/markitdown", number)
        if stored.id != int(case["snapshot_id"]):
            raise ValueError(f"upstream PR #{number}: latest snapshot differs from frozen version")
        existing = conn.execute(
            "SELECT s.id FROM pr_summaries s "
            "JOIN llm_calls c ON c.id=s.llm_call_id "
            "JOIN prompt_versions p ON p.id=s.prompt_version_id "
            "WHERE s.pull_request_id=%s AND s.status='published' "
            "AND c.provider='openrouter' AND p.content_hash=%s "
            "ORDER BY s.id DESC LIMIT 1",
            (stored.id, prompt.content_hash),
        ).fetchone()
        if existing is not None:
            records[str(number)] = {
                **_upstream_record(conn, int(existing[0]), stored.id),
                "recovered_existing": True,
            }
            _save(progress, path)
            continue
        input_tokens = 2 * int(case["estimated_prepared_tokens"]) + 5_000
        output_tokens = registry.stages["pr_summary"].reserved_output_tokens
        ceiling = (
            Decimal(2)
            * (Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate)
            / Decimal(1_000_000)
        )
        _require_room(conn, cap, ceiling)
        report_id = summarize(
            conn,
            stored,
            registry=registry,
            prompt=prompt,
            retention="full",
        )
        conn.commit()
        records[str(number)] = _upstream_record(conn, report_id, stored.id)
        _save(progress, path)
        print(
            f"upstream #{number}: report {report_id} ({records[str(number)]['status']}); "
            f"spent ${_spent(conn):.4f}",
            flush=True,
        )


def _aggregate_stage(
    conn: psycopg.Connection,
    *,
    source_id: UUID,
    progress: dict[str, Any],
    path: Path,
    cap: Decimal,
) -> None:
    if progress["aggregate"]:
        return
    source = load_source(conn, source_id)
    if source.kind != "aggregate" or len(source.inputs) != 8:
        raise ValueError("aggregate source must contain all eight exact input reports")
    expected_reports = tuple(
        str(progress["upstream"][str(number)]["report_id"]) for number in HELD_OUT_ORDER
    )
    if (
        source.altitude != "manager"
        or tuple(item.report_version_id for item in source.inputs) != expected_reports
    ):
        raise ValueError("aggregate source input versions or reader level differ from the plan")
    planned = plan_recipes(conn, AGGREGATE_RECIPES, include_primary_baselines=True)
    ceiling = sum(
        (_ceiling(item.recipe, estimate_tokens(source.prepared_text)) for item in planned),
        Decimal(0),
    )
    _require_room(conn, cap, ceiling)
    run = run_comparison(
        conn,
        source_id=source_id,
        recipe_version_ids=AGGREGATE_RECIPES,
        retention="full",
        execution_build="m3-workflow-v1",
    )
    conn.commit()
    progress["aggregate"] = {"source_id": str(source_id), **_comparison_record(run)}
    _save(progress, path)
    print(f"aggregate: {run.invocation.id}; spent ${_spent(conn):.4f}", flush=True)


def _assessment_stage(
    conn: psycopg.Connection,
    *,
    progress: dict[str, Any],
    path: Path,
    cap: Decimal,
) -> None:
    records: dict[str, Any] = progress["assessment"]
    expected_cases = int(progress["scope_case_count"])
    if len(progress["pr"]) != expected_cases or not progress["aggregate"]:
        raise ValueError("finish all scoped PR and aggregate comparisons before assessment stage")
    comparisons = list(progress["pr"].values())
    if progress["aggregate"]:
        comparisons.append(progress["aggregate"])
    assessor = load_recipe(conn, ASSESSOR)
    for comparison in comparisons:
        for member in comparison["members"]:
            if member["condition"] not in ("candidate", "model_comparison"):
                continue
            result_id = UUID(member["result_id"])
            if str(result_id) in records:
                continue
            target = load_result(conn, result_id)
            if target.status != "succeeded" or target.output is None:
                records[str(result_id)] = {"status": "not_run_target_failed"}
                _save(progress, path)
                continue
            existing = tuple(
                item
                for item in list_assessments(conn, target_result_id=result_id)
                if item.assessor_recipe_version_id == ASSESSOR
            )
            if existing:
                records[str(result_id)] = {
                    "assessment_id": str(existing[-1].id),
                    "status": existing[-1].status,
                    "recovered_existing": True,
                }
                _save(progress, path)
                continue
            source = load_source(conn, target.source_id)
            input_tokens = (
                2 * estimate_tokens(source.prepared_text)
                + estimate_tokens(json.dumps(target.output))
                + 10_000
            )
            _require_room(conn, cap, _ceiling(assessor, input_tokens))
            run = run_assessment(
                conn,
                target_result_id=result_id,
                assessor_recipe_version_id=ASSESSOR,
                retention="full",
            )
            conn.commit()
            records[str(result_id)] = {
                "assessment_id": str(run.assessment.id),
                "status": run.assessment.status,
                "call_count": run.measurements.call_count,
                "cost_status": run.measurements.cost_status,
                "model_latency_ms": run.measurements.model_latency_ms,
                "estimated_cost_usd": (
                    str(run.measurements.estimated_cost_usd)
                    if run.measurements.estimated_cost_usd is not None
                    else None
                ),
            }
            _save(progress, path)
            print(
                f"assessment {result_id}: {run.assessment.id}; spent ${_spent(conn):.4f}",
                flush=True,
            )


def main() -> None:  # noqa: PLR0912
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("pr", "upstream", "aggregate", "assess"), required=True)
    parser.add_argument("--cap-usd", type=Decimal, required=True)
    parser.add_argument("--aggregate-source-id", type=UUID)
    parser.add_argument("--scope", choices=tuple(SCOPES), default="all20")
    parser.add_argument("--progress", type=Path, default=PROGRESS_PATH)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.cap_usd <= 0:
        raise ValueError("spend cap must be positive")
    inventory_bytes = INVENTORY_PATH.read_bytes()
    inventory: dict[str, Any] = json.loads(inventory_bytes)
    cases: list[dict[str, Any]] = inventory["cases"]
    if len(cases) != 20:
        raise ValueError("source inventory must contain exactly 20 cases")
    inventory_cases: list[dict[str, Any]] = inventory["cases"]
    cases = SCOPES[args.scope](inventory_cases)
    if (
        args.scope == "heldout8"
        and tuple(int(item["pr_number"]) for item in cases) != HELD_OUT_ORDER
    ):
        raise ValueError("heldout8 scope does not match the frozen aggregate input order")
    progress = _load_progress(args.progress, hashlib.sha256(inventory_bytes).hexdigest())
    if progress.get("scope") not in (None, args.scope):
        raise ValueError("progress belongs to a different workflow scope")
    progress["scope"] = args.scope
    progress["scope_case_count"] = len(cases)
    with connect(load_settings().database_url) as conn:
        print(
            f"phase {args.phase}; {len(cases)} sources; recorded OpenRouter spend "
            f"${_spent(conn):.4f}; cap ${args.cap_usd:.2f}"
        )
        if not args.execute:
            print("Dry run only. Add --execute after the owner approves the spend cap.")
            return
        if args.phase != "upstream":
            if not SPEC_PATH.exists():
                raise ValueError("freeze the workflow run spec before held-out comparisons")
            specification = json.loads(SPEC_PATH.read_text())
            if (
                Decimal(specification["approved_spend_cap_usd"]) != args.cap_usd
                or specification.get("scope") != args.scope
                or specification["source_inventory"]["sha256"]
                != hashlib.sha256(inventory_bytes).hexdigest()
            ):
                raise ValueError("spend cap or source inventory differs from frozen run spec")
            if (
                args.phase == "aggregate"
                and str(args.aggregate_source_id) != specification["aggregate"]["source_id"]
            ):
                raise ValueError("aggregate source differs from frozen run spec")
        if args.phase == "pr":
            _pr_stage(conn, cases=cases, progress=progress, path=args.progress, cap=args.cap_usd)
        elif args.phase == "upstream":
            _upstream_stage(
                conn, cases=cases, progress=progress, path=args.progress, cap=args.cap_usd
            )
        elif args.phase == "aggregate":
            if args.aggregate_source_id is None:
                raise ValueError("--aggregate-source-id is required for the aggregate phase")
            _aggregate_stage(
                conn,
                source_id=args.aggregate_source_id,
                progress=progress,
                path=args.progress,
                cap=args.cap_usd,
            )
        else:
            _assessment_stage(conn, progress=progress, path=args.progress, cap=args.cap_usd)


if __name__ == "__main__":
    main()
