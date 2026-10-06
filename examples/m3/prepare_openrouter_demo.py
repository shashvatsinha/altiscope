"""Save exact OpenRouter M3 workflow recipe versions without model calls.

Each invocation appends new recipe versions; retain its printed IDs together.
"""

from __future__ import annotations

import json

from altiscope.config import load_settings
from altiscope.llm.registry import Registry
from altiscope.prompts import load_prompt
from altiscope.store.baselines import register_primary_baseline
from altiscope.store.db import connect
from altiscope.store.recipes import RecipeOverrides, create_recipe


def main() -> None:
    settings = load_settings()
    # Pin the checked-in multi-provider registry, regardless of a local .env override.
    registry = Registry.load(settings.prompts_dir.parent / "config/models.yaml")
    plan: dict[str, object] = {"kind": "m3-openrouter-workflow-preparation-v1"}
    with connect(settings.database_url) as conn:
        recipes: list[dict[str, object]] = []
        for stage, prompt_path, baseline_path in (
            ("pr_summary", "pr_summary/v3.md", "baseline/pr_summary-v1.md"),
            ("aggregate", "aggregate/v4.md", "baseline/aggregate-v1.md"),
        ):
            for name, model in (
                ("anthropic", "openrouter-anthropic"),
                ("google", "openrouter-google"),
            ):
                recipe = create_recipe(
                    conn,
                    name=f"m3-demo-{stage}-{name}",
                    registry_key=model,
                    prompt=load_prompt(settings.prompts_dir / prompt_path),
                    registry=registry,
                    overrides=RecipeOverrides(effort="low", reserved_output_tokens=4096),
                )
                baseline = register_primary_baseline(
                    conn,
                    recipe_version_id=recipe.id,
                    prompt=load_prompt(settings.prompts_dir / baseline_path),
                )
                for item, condition in (
                    (recipe, "candidate"),
                    (baseline.recipe, "primary_baseline"),
                ):
                    recipes.append(
                        {
                            "stage": stage,
                            "condition": condition,
                            "recipe_id": str(item.id),
                            "name": item.name,
                            "version": item.version,
                            "configuration_hash": item.configuration_hash,
                            "model": item.config.model.underlying_model_id,
                            "prompt_version": item.prompt.version,
                            "prompt_hash": item.prompt.content_hash,
                        }
                    )
        assessor = create_recipe(
            conn,
            name="m3-demo-independent-assessor",
            registry_key="openrouter-openai",
            prompt=load_prompt(settings.prompts_dir / "verify/v2.md"),
            registry=registry,
            overrides=RecipeOverrides(effort="low", reserved_output_tokens=2048),
        )
        recipes.append(
            {
                "stage": "verify",
                "condition": "assessor",
                "recipe_id": str(assessor.id),
                "name": assessor.name,
                "version": assessor.version,
                "configuration_hash": assessor.configuration_hash,
                "model": assessor.config.model.underlying_model_id,
                "prompt_version": assessor.prompt.version,
                "prompt_hash": assessor.prompt.content_hash,
            }
        )
        plan["recipes"] = recipes
    print(json.dumps(plan, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
