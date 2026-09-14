from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from typer.testing import CliRunner

from altiscope.aggregate.inputs import render_inputs
from altiscope.cli.main import app
from altiscope.comparison.service import run_comparison
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.llm.execution import request_tokens as structured_request_tokens
from altiscope.llm.provider import Usage
from altiscope.prompts import load_prompt
from altiscope.schemas.pr_summary import PrReviewOutput
from altiscope.store.baselines import generation_condition_hash, register_primary_baseline
from altiscope.store.comparisons import freeze_aggregate_source, freeze_pr_source, load_result
from altiscope.store.recipes import RecipeOverrides, RecipeVersion, create_recipe
from altiscope.summarize.fixture import FixtureProvider, fixture_registry
from tests.conftest import REPO_ROOT
from tests.test_aggregate_generation import good_output

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres"),
]


def _freeze_pr(conn: psycopg.Connection, snapshot: PullRequestSnapshot):
    from altiscope.store.snapshots import save_snapshot
    from altiscope.summarize.context import render_user_prompt
    from altiscope.summarize.service import prepare

    suffix = uuid4().hex[:12]
    frozen = snapshot.model_copy(
        update={
            "repository": f"acme/comparison-service-{suffix}",
            "html_url": f"https://github.com/acme/comparison-service-{suffix}/pull/42",
        }
    )
    stored = save_snapshot(
        conn,
        frozen,
        repository_id=910_000_000 + int(uuid4().hex[:6], 16),
        default_branch="main",
        raw={"comparison_service": True},
    )
    context = prepare(frozen)
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
    return source, stored, context


def _recipes(
    conn: psycopg.Connection,
    *,
    stage: str = "pr_summary",
    overrides: tuple[RecipeOverrides, RecipeOverrides] | None = None,
) -> tuple[RecipeVersion, RecipeVersion]:
    registry = fixture_registry()
    prompt = load_prompt(
        REPO_ROOT / "prompts" / stage / ("v3.md" if stage == "pr_summary" else "v4.md")
    )
    supplied = overrides or (RecipeOverrides(), RecipeOverrides())
    name = f"service-{stage}-{uuid4().hex}"
    return tuple(
        create_recipe(
            conn,
            name=name,
            registry_key="fixture",
            prompt=prompt,
            registry=registry,
            overrides=item,
        )
        for item in supplied
    )  # type: ignore[return-value]


def _factory(
    responses: dict[UUID, list[str]], providers: dict[UUID, FixtureProvider]
) -> Callable[[RecipeVersion], FixtureProvider]:
    def create(recipe: RecipeVersion) -> FixtureProvider:
        provider = FixtureProvider(responses[recipe.id])
        providers[recipe.id] = provider
        return provider

    return create


def test_default_baseline_expansion_reuse_force_history_and_cache_isolation(
    database: str, snapshot: PullRequestSnapshot
):
    from altiscope.llm.router import route
    from altiscope.store.accounts import save_account
    from altiscope.summarize.context import render_user_prompt
    from altiscope.summarize.generate import generate_account, request_tokens

    with psycopg.connect(database) as conn:
        source, stored, context = _freeze_pr(conn, snapshot)
        first, second = _recipes(conn)
        baseline_prompt = load_prompt(REPO_ROOT / "prompts/baseline/pr_summary-v1.md")
        first_baseline = register_primary_baseline(
            conn, recipe_version_id=first.id, prompt=baseline_prompt
        )
        second_baseline = register_primary_baseline(
            conn, recipe_version_id=second.id, prompt=baseline_prompt
        )
        assert first_baseline.recipe.id == second_baseline.recipe.id
        assert generation_condition_hash(first) == generation_condition_hash(first_baseline.recipe)
        assert first.prompt.content_hash != first_baseline.recipe.prompt.content_hash

        # A production-current result with the same source/model does not satisfy the
        # comparison cache, and comparison writes do not replace it.
        production_provider = FixtureProvider(['{"review":"Production report."}'])
        generated = generate_account(
            context,
            production_provider,
            first.config.to_registry().models["fixture"],
            system=first.prompt.body,
            max_tokens=first.config.generation.reserved_output_tokens,
            effort=first.config.generation.requested_effort,
            input_budget=first.config.budget.input_limit,
        )
        production_id = save_account(
            conn,
            stored.id,
            context,
            generated=generated,
            prompt=first.prompt,
            decision=route(
                first.config.to_registry(),
                "pr_summary",
                request_tokens(first.prompt.body, render_user_prompt(context)),
            ),
            registry=first.config.to_registry(),
            retention="full",
        )

        baseline_id = first_baseline.recipe.id
        responses = {
            first.id: ['{"review":"Candidate one."}'],
            second.id: ['{"review":"Candidate two."}'],
            baseline_id: ['{"review":"Minimal baseline."}'],
        }
        providers: dict[UUID, FixtureProvider] = {}
        initial = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=(first.id, second.id, baseline_id),
            retention="hashes_only",
            execution_build="service-test",
            provider_factory=_factory(responses, providers),
        )
        assert initial.new_call_count == 3
        assert sum(provider.calls for provider in providers.values()) == 3
        assert [item.condition_label for item in initial.members] == [
            "candidate",
            "candidate",
            "primary_baseline",
        ]
        assert initial.members[2].baseline_for_recipe_version_ids == (first.id, second.id)
        assert all(item.result.output is not None for item in initial.members)
        assert conn.execute(
            "SELECT id FROM pr_summaries WHERE pull_request_id=%s AND is_current",
            (stored.id,),
        ).fetchall() == [(production_id,)]

        def unexpected(_: RecipeVersion) -> FixtureProvider:
            raise AssertionError("a compatible cache hit must not build or call a provider")

        repeated = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=(first.id, second.id),
            retention="full",
            execution_build="service-test-rerun",
            provider_factory=unexpected,
        )
        assert repeated.new_call_count == 0
        assert repeated.new_cost_status == "not_incurred"
        assert all(item.disposition == "reused" for item in repeated.members)
        assert [item.result.id for item in repeated.members] == [
            item.result.id for item in initial.members
        ]
        assert all(item.current.call_count == 0 for item in repeated.members)
        assert all(item.origin.call_count == 1 for item in repeated.members)
        assert all(item.result.origin_retention == "hashes_only" for item in repeated.members)

        forced_providers: dict[UUID, FixtureProvider] = {}
        forced = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=(first.id, second.id),
            retention="full",
            execution_build="service-test-force",
            regenerate=True,
            provider_factory=_factory(responses, forced_providers),
        )
        assert forced.new_call_count == 3
        assert all(item.disposition == "generated" for item in forced.members)
        assert {item.result.id for item in forced.members}.isdisjoint(
            {item.result.id for item in initial.members}
        )
        assert conn.execute(
            "SELECT count(*) FROM comparison_run_results WHERE source_id=%s", (source.id,)
        ).fetchone() == (6,)
        # hashes_only retains validated output while dropping raw request/response payloads.
        call_id = initial.members[0].result.call_ids[0]
        assert load_result(conn, initial.members[0].result.id).output == {
            "review": "Candidate one."
        }
        assert conn.execute(
            "SELECT request_payload,response_text FROM llm_calls WHERE id=%s", (call_id,)
        ).fetchone() == (None, None)

        changed_source = freeze_pr_source(
            conn,
            snapshot_id=stored.id,
            preparation_document=source.preparation_document,
            prepared_text=source.prepared_text + "\nFrozen preparation revision.",
            preparation_contract={"renderer": "pr-context-v2", "facts": "v1", "policy": "v1"},
        )
        changed_providers: dict[UUID, FixtureProvider] = {}
        changed = run_comparison(
            conn,
            source_id=changed_source.id,
            recipe_version_ids=(first.id, second.id),
            retention="full",
            execution_build="source-change-test",
            include_primary_baselines=False,
            provider_factory=_factory(responses, changed_providers),
        )
        assert changed.new_call_count == 2
        assert all(item.disposition == "generated" for item in changed.members)


def test_repairs_partial_failure_and_oversized_preflight_are_counted(
    database: str, snapshot: PullRequestSnapshot
):
    with psycopg.connect(database) as conn:
        source, _, _ = _freeze_pr(conn, snapshot)
        repaired_recipe, failed_recipe = _recipes(conn)
        providers: dict[UUID, FixtureProvider] = {}
        run = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=(repaired_recipe.id, failed_recipe.id),
            retention="full",
            execution_build="repair-test",
            include_primary_baselines=False,
            provider_factory=_factory(
                {
                    repaired_recipe.id: ['{"review":" "}', '{"review":"Repaired."}'],
                    failed_recipe.id: ["{}", "{}"],
                },
                providers,
            ),
        )
        assert run.new_call_count == 4
        assert run.new_cost_status == "unavailable"
        assert [item.result.status for item in run.members] == ["succeeded", "invalid_output"]
        assert [len(item.result.call_ids) for item in run.members] == [2, 2]
        assert load_result(conn, run.members[0].result.id).output == {"review": "Repaired."}
        assert load_result(conn, run.members[1].result.id).output is None
        assert conn.execute(
            "SELECT status FROM comparison_invocations WHERE id=%s", (run.invocation.id,)
        ).fetchone() == ("completed",)

        normal, tiny = _recipes(
            conn,
            overrides=(
                RecipeOverrides(reserved_output_tokens=1),
                RecipeOverrides(reserved_output_tokens=1, input_budget_fraction=0.001),
            ),
        )
        oversized_providers: dict[UUID, FixtureProvider] = {}
        oversized = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=(normal.id, tiny.id),
            retention="full",
            execution_build="budget-test",
            include_primary_baselines=False,
            provider_factory=_factory(
                {
                    normal.id: ['{"review":"Fits."}'],
                    tiny.id: ['{"review":"Must not be called."}'],
                },
                oversized_providers,
            ),
        )
        assert [item.result.status for item in oversized.members] == [
            "succeeded",
            "preflight_failed",
        ]
        assert oversized.members[1].result.call_ids == ()
        assert oversized_providers[tiny.id].calls == 0
        assert oversized.new_call_count == 1


def test_repair_budget_cost_estimates_and_missing_credentials(
    database: str, snapshot: PullRequestSnapshot, monkeypatch: pytest.MonkeyPatch
):
    with psycopg.connect(database) as conn:
        source, _, _ = _freeze_pr(conn, snapshot)
        registry = fixture_registry()
        registry.models["fixture"].input_usd_per_mtok = 2
        registry.models["fixture"].output_usd_per_mtok = 4
        prompt = load_prompt(REPO_ROOT / "prompts/pr_summary/v3.md")
        required = structured_request_tokens(
            system=prompt.body,
            user=source.prepared_text,
            output_type=PrReviewOutput,
            schema_envelope_allowance=256,
        )
        registry.models["fixture"].context_window = required + 1
        first = create_recipe(
            conn,
            name="measured-repair-" + uuid4().hex,
            registry_key="fixture",
            prompt=prompt,
            registry=registry,
            overrides=RecipeOverrides(
                reserved_output_tokens=1, input_budget_fraction=1, repair_limit=1
            ),
        )
        second = create_recipe(
            conn,
            name="measured-success-" + uuid4().hex,
            registry_key="fixture",
            prompt=prompt,
            registry=registry,
            overrides=RecipeOverrides(
                reserved_output_tokens=1, input_budget_fraction=1, repair_limit=0
            ),
        )

        class MeasuredFixture(FixtureProvider):
            def generate_structured(self, **kwargs):  # type: ignore[no-untyped-def]
                result = super().generate_structured(**kwargs)
                return replace(result, usage=Usage(10, 5), latency_ms=7)

        run = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=(first.id, second.id),
            retention="full",
            execution_build="measured-test",
            include_primary_baselines=False,
            provider_factory=lambda recipe: MeasuredFixture(
                ["{}"] if recipe.id == first.id else ['{"review":"Measured success."}']
            ),
        )
        # The first real call is retained, but its larger repair request is rejected
        # before a second call. The sibling still succeeds.
        assert [item.result.status for item in run.members] == ["invalid_output", "succeeded"]
        assert [item.current.call_count for item in run.members] == [1, 1]
        assert run.new_call_count == 2
        assert run.new_cost_status == "complete"
        assert run.new_estimated_cost_usd == Decimal("0.00008000")

        missing_name = "ALTISCOPE_TEST_MISSING_" + uuid4().hex.upper()
        monkeypatch.delenv(missing_name, raising=False)
        missing_registry = fixture_registry()
        missing_registry.providers["fixture"].api_key_env = missing_name
        missing_first = create_recipe(
            conn,
            name="missing-credential-a-" + uuid4().hex,
            registry_key="fixture",
            prompt=prompt,
            registry=missing_registry,
        )
        missing_second = create_recipe(
            conn,
            name="missing-credential-b-" + uuid4().hex,
            registry_key="fixture",
            prompt=prompt,
            registry=missing_registry,
        )
        missing = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=(missing_first.id, missing_second.id),
            retention="full",
            execution_build="credential-test",
            include_primary_baselines=False,
        )
        assert missing.new_call_count == 0
        assert missing.new_cost_status == "not_incurred"
        assert all(item.result.status == "preflight_failed" for item in missing.members)
        assert all(item.result.call_ids == () for item in missing.members)
        assert conn.execute(
            "SELECT array_agg(error_code ORDER BY created_at) FROM comparison_run_results "
            "WHERE id=ANY(%s)",
            ([item.result.id for item in missing.members],),
        ).fetchone() == (["credentials", "credentials"],)


def test_aggregate_members_receive_identical_frozen_input_and_model_changes_are_labeled(
    database: str, snapshot: PullRequestSnapshot
):
    from altiscope.llm.router import route
    from altiscope.store.accounts import save_account
    from altiscope.store.aggregates import load_pr_input
    from altiscope.summarize.context import render_user_prompt
    from altiscope.summarize.generate import generate_account, request_tokens

    with psycopg.connect(database) as conn:
        _, stored, context = _freeze_pr(conn, snapshot)
        registry = fixture_registry()
        pr_prompt = load_prompt(REPO_ROOT / "prompts/pr_summary/v3.md")
        generated = generate_account(
            context,
            FixtureProvider(['{"review":"Saved aggregate input."}']),
            registry.models["fixture"],
            system=pr_prompt.body,
            max_tokens=4096,
            effort="low",
            input_budget=100_000,
        )
        report_id = save_account(
            conn,
            stored.id,
            context,
            generated=generated,
            prompt=pr_prompt,
            decision=route(
                registry,
                "pr_summary",
                request_tokens(pr_prompt.body, render_user_prompt(context)),
            ),
            registry=registry,
            retention="full",
        )
        repository_row = conn.execute(
            "SELECT repository_id FROM pull_requests WHERE id=%s", (stored.id,)
        ).fetchone()
        assert repository_row is not None
        repository_id = int(repository_row[0])
        supplied = (load_pr_input(conn, report_id),)
        prepared = render_inputs("Summarize for a manager.", supplied)
        source = freeze_aggregate_source(
            conn,
            repository_id=repository_id,
            inputs=supplied,
            query={"since": "2026-06-01", "until": "2026-06-30", "inclusive": True},
            altitude="manager",
            prepared_text=prepared,
            preparation_contract={"renderer": "aggregate-inputs-v1"},
        )
        first, _ = _recipes(conn, stage="aggregate")
        registry.models["fixture-other"] = registry.models["fixture"].model_copy(
            update={
                "id": "fixture-other",
                "model_name": "fixture-other",
                "underlying_model_id": "fixture/other-v1",
                "underlying_model_evidence": "test fixture",
            }
        )
        other = create_recipe(
            conn,
            name="aggregate-other-" + uuid4().hex,
            registry_key="fixture-other",
            prompt=load_prompt(REPO_ROOT / "prompts/aggregate/v4.md"),
            registry=registry,
        )
        aggregate_baseline_prompt = load_prompt(REPO_ROOT / "prompts/baseline/aggregate-v1.md")
        first_baseline = register_primary_baseline(
            conn, recipe_version_id=first.id, prompt=aggregate_baseline_prompt
        )
        other_baseline = register_primary_baseline(
            conn, recipe_version_id=other.id, prompt=aggregate_baseline_prompt
        )
        assert first_baseline.recipe.id != other_baseline.recipe.id
        seen_users: dict[UUID, list[str]] = {}

        class RecordingFixture(FixtureProvider):
            def __init__(self, recipe_id: UUID):
                super().__init__([good_output().model_dump_json()])
                self.recipe_id = recipe_id

            def generate_structured(self, **kwargs):  # type: ignore[no-untyped-def]
                seen_users.setdefault(self.recipe_id, []).append(kwargs["user"])
                return super().generate_structured(**kwargs)

        run = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=(first.id, other.id, first_baseline.recipe.id),
            retention="full",
            execution_build="aggregate-test",
            provider_factory=lambda recipe: RecordingFixture(recipe.id),
        )
        assert [item.condition_label for item in run.members] == [
            "candidate",
            "model_comparison",
            "primary_baseline",
            "primary_baseline",
        ]
        assert seen_users == {
            first.id: [prepared],
            other.id: [prepared],
            first_baseline.recipe.id: [prepared],
            other_baseline.recipe.id: [prepared],
        }
        assert all(item.result.status == "succeeded" for item in run.members)


def test_comparison_cli_runs_offline_with_default_baseline(
    database: str, snapshot: PullRequestSnapshot, monkeypatch: pytest.MonkeyPatch
):
    with psycopg.connect(database) as conn:
        source, _, _ = _freeze_pr(conn, snapshot)
        first, second = _recipes(conn)
        baseline_prompt = load_prompt(REPO_ROOT / "prompts/baseline/pr_summary-v1.md")
        register_primary_baseline(conn, recipe_version_id=first.id, prompt=baseline_prompt)
        register_primary_baseline(conn, recipe_version_id=second.id, prompt=baseline_prompt)

    built: list[FixtureProvider] = []

    def offline(_: RecipeVersion) -> FixtureProvider:
        provider = FixtureProvider(['{"review":"Offline comparison fixture."}'])
        built.append(provider)
        return provider

    monkeypatch.setattr("altiscope.comparison.service._default_provider", offline)
    monkeypatch.chdir(REPO_ROOT)
    result = CliRunner().invoke(
        app,
        [
            "comparisons",
            "run",
            str(source.id),
            "--recipe",
            str(first.id),
            "--recipe",
            str(second.id),
        ],
    )
    assert result.exit_code == 0, result.exception
    assert "primary_baseline" in result.output
    assert "Current invocation: 3 model calls" in result.output
    assert sum(provider.calls for provider in built) == 3
