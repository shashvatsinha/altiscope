"""Create a synthetic frozen comparison without a network or paid model call.

Run from the repository root after `altiscope db migrate`.
"""

from __future__ import annotations

from uuid import uuid4

from altiscope.comparison.service import run_comparison
from altiscope.config import load_settings
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.prompts import load_prompt
from altiscope.store.baselines import register_primary_baseline
from altiscope.store.comparisons import freeze_pr_source
from altiscope.store.db import connect
from altiscope.store.recipes import RecipeOverrides, create_recipe
from altiscope.store.snapshots import save_snapshot
from altiscope.summarize.context import render_user_prompt
from altiscope.summarize.fixture import FixtureProvider, fixture_registry
from altiscope.summarize.service import prepare


def main() -> None:
    settings = load_settings()
    snapshot = PullRequestSnapshot.model_validate_json(
        (settings.prompts_dir.parent / "examples/m1/snapshot.json").read_text()
    )
    suffix = uuid4().hex[:8]
    snapshot = snapshot.model_copy(
        update={
            "repository": f"acme/offline-m3-{suffix}",
            "html_url": f"https://github.com/acme/offline-m3-{suffix}/pull/42",
        }
    )
    registry = fixture_registry()
    prompt = load_prompt(settings.prompts_dir / "pr_summary/v3.md")
    baseline_prompt = load_prompt(settings.prompts_dir / "baseline/pr_summary-v1.md")
    with connect(settings.database_url) as conn:
        stored = save_snapshot(
            conn,
            snapshot,
            repository_id=900_000_000 + int(suffix[:6], 16),
            default_branch="main",
            raw={"example": "m3-offline"},
        )
        context = prepare(snapshot)
        source = freeze_pr_source(
            conn,
            snapshot_id=stored.id,
            preparation_document={
                "facts": context.facts.model_dump(mode="json"),
                "manifest": context.manifest.model_dump(mode="json"),
            },
            prepared_text=render_user_prompt(context),
            preparation_contract={"renderer": "pr-context-v1", "facts": "v1", "policy": "v1"},
        )
        recipes = tuple(
            create_recipe(
                conn,
                name=f"offline-m3-{suffix}-{index}",
                registry_key="fixture",
                prompt=prompt,
                registry=registry,
                overrides=RecipeOverrides(reserved_output_tokens=limit),
            )
            for index, limit in enumerate((4096, 2048), 1)
        )
        for recipe in recipes:
            register_primary_baseline(conn, recipe_version_id=recipe.id, prompt=baseline_prompt)
        run = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=tuple(recipe.id for recipe in recipes),
            retention="full",
            execution_build="m3-offline-example",
            provider_factory=lambda recipe: FixtureProvider(
                ['{"review":"A lock now guards run() and a test covers the change."}']
            ),
        )
    print(f"Frozen source: {source.id}")
    print(f"Invocation: {run.invocation.id}")
    for member in run.members:
        print(f"{member.condition_label}: {member.result.id} ({member.recipe.id})")
    print(f"Inspect: altiscope show-comparison {run.invocation.id} --verbose")
    print(f"Review: altiscope comparisons review {run.members[0].result.id} \\")
    print("  --reviewer reviewer-t1 --case-id m3-dev-pr-001 --case-group development \\")
    print('  --familiarity domain --familiarity-basis "Synthetic source inspection"')


if __name__ == "__main__":
    main()
