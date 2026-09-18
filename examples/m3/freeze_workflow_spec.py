"""Freeze the exact operational run after upstream reports, before comparisons.

The generated JSON is immutable. It retains source, protocol, dataset, config,
prompt, and schema content as well as hashes and exact aggregate input versions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from run_openrouter_workflow import (
    AGGREGATE_RECIPES,
    ASSESSOR,
    HELD_OUT_ORDER,
    INVENTORY_PATH,
    PR_RECIPES,
    PROGRESS_PATH,
)

from altiscope import __version__
from altiscope.comparison.service import plan_recipes
from altiscope.config import load_settings
from altiscope.store.comparisons import load_source
from altiscope.store.db import connect
from altiscope.store.recipes import load_recipe

SPEC_PATH = Path("docs/evaluation/m3-workflow-run-spec-v1.json")


def _artifact(path: Path) -> dict[str, str]:
    raw = path.read_bytes()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content": raw.decode("utf-8"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate-source-id", type=UUID, required=True)
    parser.add_argument("--cap-usd", type=Decimal, required=True)
    parser.add_argument("--operator", required=True)
    args = parser.parse_args()
    if SPEC_PATH.exists():
        raise ValueError(f"immutable run spec already exists: {SPEC_PATH}")
    if args.cap_usd <= 0 or not args.operator.strip():
        raise ValueError("approved spend cap and operator are required")

    settings = load_settings()
    inventory = json.loads(INVENTORY_PATH.read_text())
    if len(inventory["cases"]) != 20:
        raise ValueError("source inventory must contain exactly 20 cases")
    progress = json.loads(PROGRESS_PATH.read_text())
    if (
        progress.get("source_inventory_sha256")
        != hashlib.sha256(INVENTORY_PATH.read_bytes()).hexdigest()
    ):
        raise ValueError("upstream progress belongs to another source inventory")
    upstream = progress["upstream"]
    if set(upstream) != {str(number) for number in HELD_OUT_ORDER}:
        raise ValueError("all eight upstream reports are required before freeze")
    if any(upstream[str(number)]["status"] != "published" for number in HELD_OUT_ORDER):
        raise ValueError("every aggregate input report must be successful")
    expected_reports = tuple(str(upstream[str(number)]["report_id"]) for number in HELD_OUT_ORDER)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    with connect(settings.database_url) as conn:
        for item in inventory["cases"]:
            source = load_source(conn, UUID(item["source_id"]))
            if (
                source.pull_request_id != item["snapshot_id"]
                or source.content_hash != item["source_hash"]
                or source.prepared_text_hash != item["prepared_text_hash"]
            ):
                raise ValueError(f"frozen PR source changed: {item['case_id']}")
        aggregate = load_source(conn, args.aggregate_source_id)
        if aggregate.kind != "aggregate" or aggregate.altitude != "manager":
            raise ValueError("aggregate source has the wrong stage or altitude")
        if tuple(item.report_version_id for item in aggregate.inputs) != expected_reports:
            raise ValueError("aggregate source inputs differ from exact upstream reports")
        if aggregate.query is None or (
            aggregate.query.get("since") != "2025-05-21T00:00:00Z"
            or aggregate.query.get("until") != "2025-05-21T23:59:59.999999Z"
        ):
            raise ValueError("aggregate window differs from selected dataset")
        recipes = []
        planned = (
            *plan_recipes(conn, PR_RECIPES, include_primary_baselines=True),
            *plan_recipes(conn, AGGREGATE_RECIPES, include_primary_baselines=True),
        )
        condition_by_id = {item.recipe.id: item for item in planned}
        for recipe_id in (*condition_by_id, ASSESSOR):
            recipe = load_recipe(conn, recipe_id)
            schema_row = conn.execute(
                "SELECT schema_document FROM output_schema_versions WHERE id=%s",
                (recipe.schema_id,),
            ).fetchone()
            assert schema_row is not None
            recipes.append(
                {
                    "id": str(recipe.id),
                    "name": recipe.name,
                    "version": recipe.version,
                    "stage": recipe.stage,
                    "condition": (
                        condition_by_id[recipe_id].condition_label
                        if recipe_id in condition_by_id
                        else "assessor"
                    ),
                    "baseline_for_recipe_version_ids": (
                        [
                            str(value)
                            for value in condition_by_id[recipe_id].baseline_for_recipe_version_ids
                        ]
                        if recipe_id in condition_by_id
                        else []
                    ),
                    "configuration_hash": recipe.configuration_hash,
                    "configuration": recipe.config.model_dump(mode="json"),
                    "prompt_content": recipe.prompt.source_text,
                    "prompt_sha256": recipe.prompt.content_hash,
                    "schema_document": schema_row[0],
                    "schema_hash": recipe.config.output_contract.schema_hash,
                }
            )
        aggregate_inputs = [
            {
                "ordinal": ordinal,
                "pr_number": number,
                "report_version_id": report.report_version_id,
                "rendered_text_sha256": hashlib.sha256(report.text.encode()).hexdigest(),
                "source_hash": report.source_hash,
                "pr_urls": list(report.pr_urls),
                "upstream_call_count": upstream[str(number)]["call_count"],
                "upstream_cost_status": upstream[str(number)]["cost_status"],
                "upstream_estimated_cost_usd": upstream[str(number)]["estimated_cost_usd"],
            }
            for ordinal, (number, report) in enumerate(
                zip(HELD_OUT_ORDER, aggregate.inputs, strict=True), 1
            )
        ]

    specification = {
        "id": "m3-workflow-run-v1",
        "purpose": "operational workflow demonstration; not a qualified quality study",
        "frozen_at_utc": datetime.now(UTC).isoformat(),
        "operator": args.operator.strip(),
        "framework": {"package_version": __version__, "git_commit": commit},
        "approved_spend_cap_usd": str(args.cap_usd),
        "expected_initial_calls": 134,
        "expected_pr_comparison_members": 80,
        "expected_aggregate_comparison_members": 4,
        "expected_assessments_if_all_candidates_succeed": 42,
        "protocol": _artifact(Path("docs/evaluation/m3-protocol-v1.md")),
        "dataset": _artifact(Path("docs/evaluation/m3-eval-set-v1.md")),
        "source_inventory": _artifact(INVENTORY_PATH),
        "model_registry": _artifact(Path("config/models.yaml")),
        "release_scope_decision": _artifact(Path("docs/adr/0013-m3-workflow-release-scope.md")),
        "recipes": recipes,
        "aggregate": {
            "case_id": "m3-heldout-manager-day-2025-05-21",
            "experiment_scope": "single_step",
            "repository_github_id": 888_092_115,
            "since_utc_inclusive": "2025-05-21T00:00:00Z",
            "until_utc_inclusive": "2025-05-21T23:59:59.999999Z",
            "source_id": str(aggregate.id),
            "source_hash": aggregate.content_hash,
            "prepared_text_hash": aggregate.prepared_text_hash,
            "query": aggregate.query,
            "inputs": aggregate_inputs,
        },
        "review_arrangement": {
            "owner_role": "workflow reviewer",
            "markitdown_source_qualification": False,
            "quality_judgments": "not_collected",
            "presentation_order": "no blinded quality comparison claimed",
        },
    }
    with SPEC_PATH.open("x") as output:
        json.dump(specification, output, indent=2, sort_keys=True)
        output.write("\n")
    print(f"Frozen workflow specification: {SPEC_PATH}")
    print(f"SHA-256: {hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
