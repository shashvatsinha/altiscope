"""Prompt-only primary baselines for immutable generation recipes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

import psycopg

from altiscope.prompts import Prompt
from altiscope.store.recipes import RecipeVersion, create_recipe_variant, load_recipe

BASELINE_PROMPT_CLASS = "minimal_summary"
DEFAULT_BASELINE_RATIONALE = (
    "Ordinary minimal summary prompt; model, endpoint, output schema, generation settings, "
    "input preparation, and single-step scope are held fixed."
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def generation_condition_hash(recipe: RecipeVersion) -> str:
    """Hash every frozen execution field except the prompt identity itself."""
    document = recipe.config.model_dump(mode="json")
    for key in ("prompt_hash", "prompt_version", "prompt_source_path"):
        document.pop(key)
    return hashlib.sha256(_canonical_json(document).encode()).hexdigest()


@dataclass(frozen=True)
class PrimaryBaseline:
    recipe: RecipeVersion
    generation_condition_hash: str
    rationale: str


def _baseline_row(conn: psycopg.Connection, recipe_version_id: UUID) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT generation_condition_hash,rationale FROM baseline_recipe_versions "
        "WHERE recipe_version_id=%s",
        (recipe_version_id,),
    ).fetchone()
    return (str(row[0]), str(row[1])) if row else None


def is_primary_baseline(conn: psycopg.Connection, recipe_version_id: UUID) -> bool:
    return _baseline_row(conn, recipe_version_id) is not None


def load_primary_baseline(
    conn: psycopg.Connection, recipe_version_id: UUID
) -> PrimaryBaseline | None:
    row = conn.execute(
        "SELECT b.baseline_recipe_version_id,b.rationale,v.generation_condition_hash "
        "FROM recipe_primary_baselines b "
        "JOIN baseline_recipe_versions v ON v.recipe_version_id=b.baseline_recipe_version_id "
        "WHERE b.recipe_version_id=%s",
        (recipe_version_id,),
    ).fetchone()
    if row is None:
        return None
    baseline = load_recipe(conn, UUID(str(row[0])))
    expected = generation_condition_hash(baseline)
    if expected != row[2]:
        raise ValueError("stored baseline generation condition hash mismatch")
    return PrimaryBaseline(baseline, expected, str(row[1]))


def register_primary_baseline(
    conn: psycopg.Connection,
    *,
    recipe_version_id: UUID,
    prompt: Prompt,
    rationale: str = DEFAULT_BASELINE_RATIONALE,
) -> PrimaryBaseline:
    """Create or share a prompt-only baseline and assign it to an exact recipe."""
    clean_rationale = " ".join(rationale.split())
    if not clean_rationale:
        raise ValueError("baseline rationale must not be blank")
    candidate = load_recipe(conn, recipe_version_id)
    if candidate.stage == "verify":
        raise ValueError("assessment recipes do not require generation baselines")
    if is_primary_baseline(conn, candidate.id):
        raise ValueError("a primary baseline does not recursively require another baseline")
    if prompt.stage != candidate.stage:
        raise ValueError("baseline prompt stage must match the candidate recipe")
    condition_hash = generation_condition_hash(candidate)
    with conn.transaction():
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"baseline:{condition_hash}:{prompt.content_hash}",),
        )
        existing_assignment = load_primary_baseline(conn, candidate.id)
        if existing_assignment is not None:
            if existing_assignment.recipe.prompt.content_hash != prompt.content_hash:
                raise ValueError(
                    "candidate already has another primary baseline; create a new candidate "
                    "recipe version to change it"
                )
            return existing_assignment
        row = conn.execute(
            "SELECT b.recipe_version_id FROM baseline_recipe_versions b "
            "JOIN recipe_versions r ON r.id=b.recipe_version_id "
            "JOIN prompt_versions p ON p.id=r.prompt_version_id "
            "WHERE b.generation_condition_hash=%s AND p.content_hash=%s "
            "ORDER BY r.created_at,r.id LIMIT 1",
            (condition_hash, prompt.content_hash),
        ).fetchone()
        if row is None:
            baseline = create_recipe_variant(
                conn,
                name=f"baseline-{candidate.stage}-{condition_hash[:12]}",
                base=candidate,
                prompt=prompt,
            )
            conn.execute(
                "INSERT INTO baseline_recipe_versions"
                "(recipe_version_id,generation_condition_hash,prompt_class,rationale) "
                "VALUES(%s,%s,%s,%s)",
                (baseline.id, condition_hash, BASELINE_PROMPT_CLASS, clean_rationale),
            )
        else:
            baseline = load_recipe(conn, UUID(str(row[0])))
        if generation_condition_hash(baseline) != condition_hash:
            raise ValueError("baseline changes more than the prompt")
        conn.execute(
            "INSERT INTO recipe_primary_baselines"
            "(recipe_version_id,baseline_recipe_version_id,rationale) VALUES(%s,%s,%s)",
            (candidate.id, baseline.id, clean_rationale),
        )
    return PrimaryBaseline(baseline, condition_hash, clean_rationale)
