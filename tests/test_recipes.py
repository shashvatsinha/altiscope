from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from altiscope.llm.registry import Registry
from altiscope.prompts import load_prompt
from altiscope.store.recipes import (
    RecipeOverrides,
    create_recipe,
    load_recipe,
    load_recipe_version,
)
from tests.conftest import REPO_ROOT

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres"),
]


def test_recipe_versions_round_trip_frozen_configuration(database: str, tmp_path: Path):
    import psycopg

    registry = Registry.load(REPO_ROOT / "config" / "models.yaml")
    source = REPO_ROOT / "prompts" / "pr_summary" / "v3.md"
    copied = tmp_path / "v3.md"
    copied.write_text(source.read_text())
    prompt = load_prompt(copied)
    name = "roundtrip-" + uuid4().hex
    with psycopg.connect(database) as conn:
        first = create_recipe(
            conn,
            name=name,
            registry_key="openrouter-anthropic",
            prompt=prompt,
            registry=registry,
            overrides=RecipeOverrides(effort="low", reserved_output_tokens=4096),
        )
        second = create_recipe(
            conn,
            name=name,
            registry_key="openrouter-anthropic",
            prompt=prompt,
            registry=registry,
            overrides=RecipeOverrides(effort="high", reserved_output_tokens=8192),
        )
        assert (first.version, second.version) == (1, 2)
        assert first.id != second.id and first.configuration_hash != second.configuration_hash

        registry.models["openrouter-anthropic"].model_name = "changed-later"
        registry.providers["openrouter"].base_url = "https://changed.invalid/v1"
        copied.write_text("removed/replaced after recipe creation")

        loaded = load_recipe(conn, first.id)
        latest = load_recipe_version(conn, name)
        assert loaded.prompt.source_text == source.read_text()
        assert loaded.config.model.wire_name == "anthropic/claude-sonnet-5"
        assert loaded.config.provider.endpoint == "https://openrouter.ai/api/v1"
        assert loaded.config.generation.requested_effort == "low"
        assert loaded.config.provider.transport_retry_limit == 0
        assert loaded.config.output_contract.version == 3
        assert loaded.config.model.underlying_model_id == "anthropic/claude-sonnet-5"
        assert loaded.config.pricing.cache_read_usd_per_mtok == 0.2
        assert loaded.config.pricing.cache_write_usd_per_mtok == 2.5
        assert loaded.config.pricing.cache_token_treatment == "separate_configured_rates"
        assert latest.id == second.id

        executable = loaded.config.to_registry()
        assert executable.models["openrouter-anthropic"].wire_name == ("anthropic/claude-sonnet-5")
        assert executable.provider_for("openrouter-anthropic").base_url == (
            "https://openrouter.ai/api/v1"
        )
        assert executable.models["openrouter-anthropic"].cache_read_usd_per_mtok == 0.2
        assert executable.models["openrouter-anthropic"].cache_write_usd_per_mtok == 2.5


def test_recipe_creation_rejects_missing_and_mismatched_references(database: str):
    import psycopg

    registry = Registry.load(REPO_ROOT / "config" / "models.yaml")
    name = "invalid-" + uuid4().hex
    with psycopg.connect(database) as conn:
        with pytest.raises(ValueError, match="unknown model registry key"):
            create_recipe(
                conn,
                name=name,
                registry_key="missing",
                prompt=load_prompt(REPO_ROOT / "prompts" / "pr_summary" / "v3.md"),
                registry=registry,
            )
        with pytest.raises(ValueError, match="unsupported output schema"):
            create_recipe(
                conn,
                name=name,
                registry_key="openrouter-anthropic",
                prompt=load_prompt(REPO_ROOT / "prompts" / "pr_summary" / "v2.md"),
                registry=registry,
            )
        with pytest.raises(ValueError, match=r"reserves .* but .* allows"):
            create_recipe(
                conn,
                name=name,
                registry_key="openrouter-anthropic",
                prompt=load_prompt(REPO_ROOT / "prompts" / "pr_summary" / "v3.md"),
                registry=registry,
                overrides=RecipeOverrides(reserved_output_tokens=999_999),
            )


def test_recipe_rejects_incompatible_anthropic_output_mode(database: str):
    import psycopg

    registry = Registry.load(REPO_ROOT / "config" / "models.yaml")
    registry.models["anthropic-sonnet"].capabilities.clear()
    with (
        psycopg.connect(database) as conn,
        pytest.raises(ValueError, match="Anthropic adapter supports only native"),
    ):
        create_recipe(
            conn,
            name="anthropic-mode-" + uuid4().hex,
            registry_key="anthropic-sonnet",
            prompt=load_prompt(REPO_ROOT / "prompts" / "pr_summary" / "v3.md"),
            registry=registry,
        )
