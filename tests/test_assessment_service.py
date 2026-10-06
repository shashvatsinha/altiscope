from __future__ import annotations

import json
import os
from dataclasses import replace
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest

from altiscope.aggregate.inputs import render_inputs
from altiscope.assessment import render_assessment, run_assessment
from altiscope.comparison.service import run_comparison
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.llm.provider import GenerationResult, Provider, Usage
from altiscope.llm.registry import Registry
from altiscope.prompts import load_prompt
from altiscope.store.comparisons import (
    ComparisonSource,
    StoredResult,
    freeze_aggregate_source,
    freeze_pr_source,
    list_assessments,
)
from altiscope.store.recipes import RecipeOverrides, RecipeVersion, create_recipe
from altiscope.summarize.fixture import FixtureProvider, fixture_registry
from tests.conftest import REPO_ROOT
from tests.test_aggregate_generation import good_output

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres"),
]


def _registry() -> Registry:
    return Registry.model_validate(
        {
            "providers": {
                "direct": {
                    "kind": "openai_compatible",
                    "base_url": "https://publisher.example/v1",
                },
                "routed": {
                    "kind": "openai_compatible",
                    "base_url": "https://router.example/v1",
                },
                "other": {
                    "kind": "openai_compatible",
                    "base_url": "https://other.example/v1",
                },
            },
            "models": {
                "producer": {
                    "provider": "direct",
                    "model_name": "fixture",
                    "display_name": "Producer",
                    "context_window": 200_000,
                    "max_output_tokens": 4096,
                    "input_usd_per_mtok": 2,
                    "output_usd_per_mtok": 10,
                    "capabilities": ["json_schema"],
                    "underlying_model_id": "publisher/generator-v1",
                    "underlying_model_evidence": "direct fixture declaration",
                    "model_version_kind": "versioned",
                },
                "producer-routed-alias": {
                    "provider": "routed",
                    "model_name": "fixture",
                    "display_name": "Producer through router",
                    "context_window": 200_000,
                    "max_output_tokens": 4096,
                    "capabilities": ["json_schema"],
                    "underlying_model_id": "publisher/generator-v1",
                    "underlying_model_evidence": "router publisher mapping",
                    "model_version_kind": "versioned",
                },
                "assessor": {
                    "provider": "other",
                    "model_name": "fixture",
                    "display_name": "Assessor",
                    "context_window": 200_000,
                    "max_output_tokens": 4096,
                    "input_usd_per_mtok": 2,
                    "output_usd_per_mtok": 10,
                    "capabilities": ["json_schema"],
                    "underlying_model_id": "other/assessor-v1",
                    "underlying_model_evidence": "other publisher declaration",
                    "model_version_kind": "versioned",
                },
                "revisioned-assessor": {
                    "provider": "other",
                    "model_name": "other/fixture/2026-01-15",
                    "display_name": "Revisioned assessor",
                    "context_window": 200_000,
                    "max_output_tokens": 4096,
                    "capabilities": ["json_schema"],
                    "underlying_model_id": "other/fixture/2026-01-15",
                    "underlying_model_evidence": "publisher/model/revision declaration",
                    "model_version_kind": "versioned",
                },
                "unknown-assessor": {
                    "provider": "other",
                    "model_name": "fixture",
                    "display_name": "Unknown assessor",
                    "context_window": 200_000,
                    "max_output_tokens": 4096,
                    "capabilities": ["json_schema"],
                },
            },
            "input_budget_fraction": 0.75,
            "stages": {
                "pr_summary": {
                    "candidates": ["producer"],
                    "effort": "low",
                    "reserved_output_tokens": 4096,
                },
                "aggregate": {
                    "candidates": ["producer"],
                    "effort": "low",
                    "reserved_output_tokens": 4096,
                },
                "verify": {
                    "candidates": ["assessor"],
                    "effort": "low",
                    "reserved_output_tokens": 1024,
                },
            },
        }
    )


class RecordingFixture(FixtureProvider):
    def __init__(
        self,
        responses: list[str],
        *,
        returned_model: str = "fixture",
        usage: Usage | None = None,
    ) -> None:
        super().__init__(responses)
        self.returned_model = returned_model
        self.usage = usage
        self.users: list[str] = []

    def generate_structured(self, **kwargs):  # type: ignore[no-untyped-def]
        self.users.append(kwargs["user"])
        result = super().generate_structured(**kwargs)
        return replace(
            result,
            model_id=self.returned_model,
            usage=self.usage or result.usage,
        )


class TerminalFixture:
    name = "terminal-fixture"

    def __init__(self, stop_reason: str) -> None:
        self.stop_reason = stop_reason
        self.calls = 0

    def generate_structured(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return GenerationResult(
            parsed=None,
            raw_text="",
            model_id="fixture",
            stop_reason=self.stop_reason,
            usage=Usage(5, 0),
            latency_ms=1,
            output_mode="native",
        )

    def count_tokens(self, **kwargs):  # type: ignore[no-untyped-def]
        return 0


def _freeze_pr(
    conn: psycopg.Connection, snapshot: PullRequestSnapshot
) -> tuple[ComparisonSource, str]:
    from altiscope.store.snapshots import save_snapshot
    from altiscope.summarize.context import render_user_prompt
    from altiscope.summarize.service import prepare

    suffix = uuid4().hex[:12]
    frozen = snapshot.model_copy(
        update={
            "repository": f"acme/assessment-{suffix}",
            "html_url": f"https://github.com/acme/assessment-{suffix}/pull/42",
        }
    )
    stored = save_snapshot(
        conn,
        frozen,
        repository_id=930_000_000 + int(uuid4().hex[:6], 16),
        default_branch="main",
        raw={"assessment": True},
    )
    context = prepare(frozen)
    prepared = render_user_prompt(context)
    source = freeze_pr_source(
        conn,
        snapshot_id=stored.id,
        preparation_document={
            "facts": context.facts.model_dump(mode="json"),
            "manifest": context.manifest.model_dump(mode="json"),
        },
        prepared_text=prepared,
        preparation_contract={"renderer": "pr-context-v1", "facts": "v1", "policy": "v1"},
    )
    return source, prepared


def _recipes(
    conn: psycopg.Connection,
    *,
    stage: str,
    producer_model: str = "producer",
) -> tuple[RecipeVersion, RecipeVersion]:
    prompt_version = "v3.md" if stage == "pr_summary" else "v4.md"
    prompt = load_prompt(REPO_ROOT / "prompts" / stage / prompt_version)
    registry = _registry()
    name = f"assessment-target-{uuid4().hex}"
    first = create_recipe(
        conn,
        name=name,
        registry_key=producer_model,
        prompt=prompt,
        registry=registry,
    )
    second = create_recipe(
        conn,
        name=name,
        registry_key=producer_model,
        prompt=prompt,
        registry=registry,
        overrides=RecipeOverrides(effort="high"),
    )
    return first, second


def _assessor(
    conn: psycopg.Connection,
    *,
    model: str = "assessor",
    overrides: RecipeOverrides | None = None,
) -> RecipeVersion:
    return create_recipe(
        conn,
        name=f"assessor-{uuid4().hex}",
        registry_key=model,
        prompt=load_prompt(REPO_ROOT / "prompts/verify/v2.md"),
        registry=_registry(),
        overrides=overrides,
    )


def _run_target(
    conn: psycopg.Connection,
    source: ComparisonSource,
    recipes: tuple[RecipeVersion, RecipeVersion],
    response: str,
    *,
    returned_model: str = "fixture",
) -> StoredResult:
    run = run_comparison(
        conn,
        source_id=source.id,
        recipe_version_ids=tuple(recipe.id for recipe in recipes),
        retention="full",
        execution_build="assessment-test",
        include_primary_baselines=False,
        provider_factory=lambda _: RecordingFixture([response], returned_model=returned_model),
    )
    return run.members[0].result


def _pr_target(
    conn: psycopg.Connection,
    snapshot: PullRequestSnapshot,
    *,
    returned_model: str = "fixture",
) -> tuple[ComparisonSource, str, StoredResult]:
    source, prepared = _freeze_pr(conn, snapshot)
    result = _run_target(
        conn,
        source,
        _recipes(conn, stage="pr_summary"),
        '{"review":"Exact saved target output."}',
        returned_model=returned_model,
    )
    return source, prepared, result


def test_pr_assessment_uses_exact_saved_input_and_is_reveal_safe(
    database: str, snapshot: PullRequestSnapshot
):
    with psycopg.connect(database) as conn:
        source, prepared, target = _pr_target(conn, snapshot)
        assessor = _assessor(conn)
        provider = RecordingFixture(
            ['{"verdict":"agree","rationale":"The complete result matches the saved change."}']
        )
        request_context = conn.execute(
            "SELECT m.invocation_id,r.origin_member_id FROM comparison_run_results r "
            "JOIN comparison_members m ON m.id=r.origin_member_id WHERE r.id=%s",
            (target.id,),
        ).fetchone()
        assert request_context is not None
        run = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=assessor.id,
            retention="full",
            requesting_invocation_id=UUID(str(request_context[0])),
            requesting_member_id=UUID(str(request_context[1])),
            provider_factory=lambda recipe: provider if recipe.id == assessor.id else None,  # type: ignore[return-value]
        )

        assessment = run.assessment
        assert assessment.status == "succeeded"
        assert assessment.verdict == "agree"
        assert assessment.requesting_invocation_id == UUID(str(request_context[0]))
        assert assessment.requesting_member_id == UUID(str(request_context[1]))
        assert assessment.input_document["source"]["source_id"] == str(source.id)  # type: ignore[index]
        assert assessment.input_document["source"]["exact_prepared_text"] == prepared  # type: ignore[index]
        assert assessment.input_document["target"]["generated_result"] == target.output  # type: ignore[index]
        sent_document = json.loads(provider.users[0].split("\n\n", 1)[1])
        assert sent_document == assessment.input_document
        assert sent_document["source"]["exact_prepared_text"] == prepared
        assert set(sent_document["source"]["preparation"]) == {"facts", "manifest"}
        assert "snapshot" not in sent_document["source"]["preparation"]
        stored_preparation = conn.execute(
            "SELECT preparation_document FROM comparison_sources WHERE id=%s", (source.id,)
        ).fetchone()
        assert stored_preparation == (source.preparation_document,)
        assert sent_document["target"]["generated_result"] == target.output
        assert run.measurements.call_count == 1
        assert list_assessments(conn, target_result_id=target.id) == (assessment,)

        hidden = render_assessment(assessment)
        assert "hidden until explicitly revealed" in hidden
        assert "matches the saved change" not in hidden
        assert hidden.endswith("\n")
        assert "verdict agree" in render_assessment(assessment, reveal=True)
        assert render_assessment(None) == ""


def test_revisioned_identity_accepts_bare_returned_model_name(
    database: str, snapshot: PullRequestSnapshot
):
    with psycopg.connect(database) as conn:
        _, _, target = _pr_target(conn, snapshot)
        assessor = _assessor(conn, model="revisioned-assessor")
        assert assessor.config.model.wire_name != "fixture"
        run = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=assessor.id,
            retention="full",
            provider_factory=lambda _: RecordingFixture(
                ['{"verdict":"agree","rationale":"The saved result is supported."}'],
                returned_model="fixture",
            ),
        )
        assert run.assessment.status == "succeeded"
        assert run.assessment.verdict == "agree"
        assert run.assessment.independence_evidence["assessor_returned_model_contradictions"] == []


def test_aggregate_assessment_retains_exact_report_versions_and_text(
    database: str, snapshot: PullRequestSnapshot
):
    from altiscope.llm.router import route
    from altiscope.store.accounts import save_account
    from altiscope.store.aggregates import load_pr_input
    from altiscope.store.snapshots import save_snapshot
    from altiscope.summarize.context import render_user_prompt
    from altiscope.summarize.generate import generate_account, request_tokens
    from altiscope.summarize.service import prepare

    with psycopg.connect(database) as conn:
        suffix = uuid4().hex[:12]
        frozen = snapshot.model_copy(
            update={
                "repository": f"acme/assessment-aggregate-{suffix}",
                "html_url": f"https://github.com/acme/assessment-aggregate-{suffix}/pull/42",
            }
        )
        stored = save_snapshot(
            conn,
            frozen,
            repository_id=940_000_000 + int(uuid4().hex[:6], 16),
            default_branch="main",
            raw={"assessment_aggregate": True},
        )
        repository_row = conn.execute(
            "SELECT repository_id FROM pull_requests WHERE id=%s", (stored.id,)
        ).fetchone()
        assert repository_row is not None
        context = prepare(frozen)
        production_registry = fixture_registry()
        prompt = load_prompt(REPO_ROOT / "prompts/pr_summary/v3.md")
        prepared_pr = render_user_prompt(context)
        generated = generate_account(
            context,
            FixtureProvider(['{"review":"Frozen report supplied to aggregate."}']),
            production_registry.models["fixture"],
            system=prompt.body,
            max_tokens=4096,
            effort="low",
            input_budget=100_000,
        )
        report_id = save_account(
            conn,
            stored.id,
            context,
            generated=generated,
            prompt=prompt,
            decision=route(
                production_registry,
                "pr_summary",
                request_tokens(prompt.body, prepared_pr),
            ),
            registry=production_registry,
            retention="full",
        )
        report_input = load_pr_input(conn, report_id)
        prepared = render_inputs("Summarize for a manager.", (report_input,))
        source = freeze_aggregate_source(
            conn,
            repository_id=int(repository_row[0]),
            inputs=(report_input,),
            query={"window": "saved"},
            altitude="manager",
            prepared_text=prepared,
            preparation_contract={"renderer": "aggregate-inputs-v1"},
        )
        target = _run_target(
            conn,
            source,
            _recipes(conn, stage="aggregate"),
            good_output().model_dump_json(),
        )
        provider = RecordingFixture(
            ['{"verdict":"inconclusive","rationale":"The saved reports are ambiguous."}']
        )
        run = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=_assessor(conn).id,
            retention="full",
            provider_factory=lambda _: provider,
        )
        assert run.assessment.status == "inconclusive"
        assert run.assessment.verdict == "inconclusive"
        inputs = run.assessment.input_document["source"]["input_versions"]  # type: ignore[index]
        assert inputs == [
            {
                "ordinal": 1,
                "kind": "pr",
                "report_version_id": str(report_id),
                "source_hash": report_input.source_hash,
            }
        ]
        assert run.assessment.input_document["source"]["exact_prepared_text"] == prepared  # type: ignore[index]
        assert "Frozen report supplied to aggregate." in provider.users[0]


def test_independence_fails_closed_for_cross_endpoint_alias_and_unknown_identity(
    database: str, snapshot: PullRequestSnapshot
):
    with psycopg.connect(database) as conn:
        _, _, target = _pr_target(conn, snapshot)
        same_model = _assessor(conn, model="producer-routed-alias")
        unknown = _assessor(conn, model="unknown-assessor")
        factory_calls: list[UUID] = []

        def factory(recipe: RecipeVersion) -> FixtureProvider:
            factory_calls.append(recipe.id)
            return FixtureProvider([])

        rejected = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=same_model.id,
            retention="full",
            provider_factory=factory,
        )
        unknown_result = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=unknown.id,
            retention="full",
            provider_factory=factory,
        )
        assert rejected.assessment.error_code == "same_underlying_model"
        assert rejected.assessment.call_ids == ()
        producer_evidence = cast(
            dict[str, object], rejected.assessment.independence_evidence["producer"]
        )
        assessor_evidence = cast(
            dict[str, object], rejected.assessment.independence_evidence["assessor"]
        )
        assert producer_evidence["endpoint"] != assessor_evidence["endpoint"]
        assert unknown_result.assessment.error_code == "independence_unknown"
        assert unknown_result.assessment.call_ids == ()
        assert factory_calls == []


def test_invocation_only_attribution_rejects_an_unrelated_target(
    database: str, snapshot: PullRequestSnapshot
):
    with psycopg.connect(database) as conn:
        _, _, first_target = _pr_target(conn, snapshot)
        _, _, unrelated_target = _pr_target(conn, snapshot)
        invocation_row = conn.execute(
            "SELECT m.invocation_id FROM comparison_run_results r "
            "JOIN comparison_members m ON m.id=r.origin_member_id WHERE r.id=%s",
            (first_target.id,),
        ).fetchone()
        assert invocation_row is not None
        provider_calls: list[UUID] = []

        def provider_factory(recipe: RecipeVersion) -> FixtureProvider:
            provider_calls.append(recipe.id)
            return FixtureProvider(
                ['{"verdict":"agree","rationale":"This must not be requested."}']
            )

        with pytest.raises(ValueError, match="requesting assessment invocation does not contain"):
            run_assessment(
                conn,
                target_result_id=unrelated_target.id,
                assessor_recipe_version_id=_assessor(conn).id,
                retention="full",
                requesting_invocation_id=UUID(str(invocation_row[0])),
                requesting_member_id=None,
                provider_factory=provider_factory,
            )
        assert provider_calls == []


def test_returned_model_contradictions_make_assessment_inconclusive(
    database: str, snapshot: PullRequestSnapshot
):
    with psycopg.connect(database) as conn:
        _, _, target = _pr_target(conn, snapshot)
        assessor = _assessor(conn)
        provider = RecordingFixture(
            ['{"verdict":"agree","rationale":"Would otherwise agree."}'],
            returned_model="other/unexpected-v9",
        )
        run = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=assessor.id,
            retention="full",
            provider_factory=lambda _: provider,
        )
        assert run.assessment.status == "inconclusive"
        assert run.assessment.verdict == "inconclusive"
        assert run.assessment.call_ids and provider.calls == 1
        assert run.assessment.independence_evidence["reason"] == "identity_contradiction"
        assert "inconclusive" not in render_assessment(run.assessment)

        _, _, contradictory_target = _pr_target(
            conn, snapshot, returned_model="publisher/unexpected-generator"
        )
        target_run = run_assessment(
            conn,
            target_result_id=contradictory_target.id,
            assessor_recipe_version_id=_assessor(conn).id,
            retention="full",
            provider_factory=lambda _: pytest.fail("assessor must not run"),
        )
        assert target_run.assessment.status == "inconclusive"
        assert target_run.assessment.call_ids == ()


def test_one_repair_total_cost_and_hashes_only_verdict_persistence(
    database: str, snapshot: PullRequestSnapshot
):
    with psycopg.connect(database) as conn:
        _, _, target = _pr_target(conn, snapshot)
        assessor = _assessor(conn)
        provider = RecordingFixture(
            [
                "{}",
                '{"verdict":"disagree","rationale":"A material omission remains."}',
            ],
            usage=Usage(100, 20),
        )
        run = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=assessor.id,
            retention="hashes_only",
            provider_factory=lambda _: provider,
        )
        assert run.assessment.status == "succeeded"
        assert run.assessment.verdict == "disagree"
        assert run.measurements.call_count == 2
        assert run.measurements.cost_status == "complete"
        assert run.measurements.estimated_cost_usd == Decimal("0.00080000")
        assert "Replace the malformed output once" in provider.users[1]
        payloads = conn.execute(
            "SELECT request_payload,response_text FROM llm_calls WHERE id=ANY(%s)",
            (list(run.assessment.call_ids),),
        ).fetchall()
        assert payloads == [(None, None), (None, None)]
        assert list_assessments(conn, target_result_id=target.id)[0].output == {
            "verdict": "disagree",
            "rationale": "A material omission remains.",
        }


@pytest.mark.parametrize(
    ("provider", "expected_status", "expected_error", "expected_calls"),
    [
        (FixtureProvider(["{}", "{}"]), "invalid_output", "invalid_output", 2),
        (TerminalFixture("refusal"), "refused", "refused", 1),
        (TerminalFixture("transport_error"), "failed", "transport", 1),
        (TerminalFixture("max_tokens"), "failed", "truncation", 1),
    ],
)
def test_terminal_assessment_failures_are_persisted(
    database: str,
    snapshot: PullRequestSnapshot,
    provider: Provider,
    expected_status: str,
    expected_error: str,
    expected_calls: int,
):
    with psycopg.connect(database) as conn:
        _, _, target = _pr_target(conn, snapshot)
        run = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=_assessor(conn).id,
            retention="full",
            provider_factory=lambda _: provider,
        )
        assert run.assessment.status == expected_status
        assert run.assessment.error_code == expected_error
        assert len(run.assessment.call_ids) == expected_calls
        assert run.assessment.verdict is None
        assert target.output == {"review": "Exact saved target output."}


def test_oversized_and_provider_preflight_failures_have_zero_attempts(
    database: str, snapshot: PullRequestSnapshot
):
    with psycopg.connect(database) as conn:
        _, _, target = _pr_target(conn, snapshot)
        tiny = _assessor(
            conn,
            overrides=RecipeOverrides(reserved_output_tokens=8, input_budget_fraction=0.0001),
        )
        oversized = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=tiny.id,
            retention="full",
            provider_factory=lambda _: RecordingFixture([]),
        )

        def incompatible_provider(_: RecipeVersion) -> Provider:
            raise ValueError("unavailable")

        incompatible = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=_assessor(conn).id,
            retention="full",
            provider_factory=incompatible_provider,
        )
        assert oversized.assessment.status == "preflight_failed"
        assert oversized.assessment.error_code == "oversized_input"
        assert oversized.assessment.call_ids == ()
        assert incompatible.assessment.error_code == "compatibility"
        assert incompatible.assessment.call_ids == ()
