from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID

import psycopg
import pytest
from typer.testing import CliRunner

from altiscope.aggregate.inputs import render_inputs
from altiscope.assessment import run_assessment
from altiscope.cli.main import app
from altiscope.comparison.inspection import render_comparison
from altiscope.comparison.service import run_comparison
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.llm.router import route
from altiscope.prompts import load_prompt
from altiscope.store.accounts import save_account
from altiscope.store.aggregates import load_pr_input
from altiscope.store.baselines import register_primary_baseline
from altiscope.store.comparisons import (
    TerminalResult,
    complete_invocation,
    create_invocation,
    freeze_aggregate_source,
    save_result,
)
from altiscope.store.evaluation import (
    EffortMeasure,
    record_exposure,
    record_post_assessment_observation,
)
from altiscope.store.recipes import create_recipe
from altiscope.summarize.context import render_user_prompt
from altiscope.summarize.fixture import FixtureProvider, fixture_registry
from altiscope.summarize.generate import generate_account, request_tokens
from tests.conftest import REPO_ROOT
from tests.test_aggregate_generation import good_output
from tests.test_assessment_service import (  # pyright: ignore[reportPrivateUsage]
    RecordingFixture,
    TerminalFixture,
    _assessor,  # pyright: ignore[reportPrivateUsage]
    _pr_target,  # pyright: ignore[reportPrivateUsage]
)
from tests.test_comparison_service import (  # pyright: ignore[reportPrivateUsage]
    _freeze_pr,  # pyright: ignore[reportPrivateUsage]
    _recipes,  # pyright: ignore[reportPrivateUsage]
)
from tests.test_review_workflow import (  # pyright: ignore[reportPrivateUsage]
    _initial,  # pyright: ignore[reportPrivateUsage]
    _new_session,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres"),
]


def test_pr_inspection_reuse_force_history_and_review_reveal(
    database: str, snapshot: PullRequestSnapshot, monkeypatch: pytest.MonkeyPatch
) -> None:
    with psycopg.connect(database) as conn:
        source, _, target = _pr_target(conn, snapshot)
        origin_row = conn.execute(
            "SELECT m.invocation_id FROM comparison_run_results r "
            "JOIN comparison_members m ON m.id=r.origin_member_id WHERE r.id=%s",
            (target.id,),
        ).fetchone()
        assert origin_row is not None
        origin_id = UUID(str(origin_row[0]))
        recipe_rows = conn.execute(
            "SELECT recipe_version_id FROM comparison_members WHERE invocation_id=%s "
            "ORDER BY ordinal",
            (origin_id,),
        ).fetchall()
        recipe_ids = tuple(UUID(str(row[0])) for row in recipe_rows)
        cached = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=recipe_ids,
            retention="hashes_only",
            execution_build="inspection-cache-test",
            include_primary_baselines=False,
            provider_factory=lambda _: pytest.fail("cached result must not call a provider"),
        )
        assert cached.new_call_count == 0
        assessor = _assessor(conn)
        assessment = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=assessor.id,
            retention="full",
            provider_factory=lambda _: RecordingFixture(
                ['{"verdict":"inconclusive","rationale":"Source ambiguity."}']
            ),
        ).assessment
        failed_assessment = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=assessor.id,
            retention="full",
            provider_factory=lambda _: TerminalFixture("refusal"),
        ).assessment
        session = _new_session(conn, result_id=target.id)
        _initial(conn, session.id)

        hidden = render_comparison(conn, cached.invocation.id)
        assert str(target.id) in hidden
        assert str(source.pull_request_id) in hidden
        assert source.historical_pr_url is not None
        assert source.historical_pr_url in hidden
        assert "reused" in hidden and "0 new calls" in hidden
        assert "not incurred" in hidden
        assert "usage unavailable" in hidden
        assert "verdict and rationale hidden" in hidden
        assert str(failed_assessment.id) in hidden and "refused" in hidden
        assert "Source ambiguity." not in hidden
        assert "correctness correct" in hidden
        assert "checking" in hidden and '"value": 0' in hidden
        assert "generation cost" in hidden and "assessment calls" in hidden
        assert "tree nodes not applicable" in hidden

        unexposed = render_comparison(conn, cached.invocation.id, review_session_id=session.id)
        assert "Source ambiguity." not in unexposed
        assert "The account matches the exact frozen source." in unexposed
        assert "Useful with minor contextual qualification." in unexposed
        exposure_id = record_exposure(
            conn,
            review_session_id=session.id,
            assessment_id=assessment.id,
            kind="guided_reveal",
            presentation_ordinal=1,
            occurred_at=datetime.now(UTC),
        )
        revealed = render_comparison(conn, cached.invocation.id, review_session_id=session.id)
        assert "verdict inconclusive" in revealed
        assert "Source ambiguity." in revealed
        assert "Source ambiguity." not in render_comparison(conn, cached.invocation.id)
        observation_id = record_post_assessment_observation(
            conn,
            review_session_id=session.id,
            exposure_id=exposure_id,
            assessment_id=assessment.id,
            assessment_status="inconclusive",
            assessment_verdict="inconclusive",
            rationale="Observation after reveal.",
            assessment_related_effort=EffortMeasure(
                component="assessment_related", status="measured", value=7, method="timer"
            ),
            post_usefulness_status="measured",
            post_usefulness_score=2,
            post_usefulness_rationale="Less useful after checking.",
            true_problem_detection=False,
            false_alarm=False,
            missed_problem=False,
            inconclusive=True,
        )
        other_session = _new_session(conn, result_id=target.id)
        _initial(conn, other_session.id)
        assert str(observation_id) not in render_comparison(conn, cached.invocation.id)
        assert str(observation_id) not in render_comparison(
            conn, cached.invocation.id, review_session_id=other_session.id
        )
        assert str(observation_id) in render_comparison(
            conn, cached.invocation.id, review_session_id=session.id
        )

        forced = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=recipe_ids,
            retention="full",
            execution_build="inspection-force-test",
            regenerate=True,
            include_primary_baselines=False,
            provider_factory=lambda _: RecordingFixture(['{"review":"Fresh result."}']),
        )
        assert forced.members[0].result.id != target.id
        fresh = render_comparison(conn, forced.invocation.id)
        assert "Fresh result." in fresh
        assert str(target.id) not in fresh
        assert "generated" in fresh
        with pytest.raises(ValueError, match="not in this invocation"):
            render_comparison(conn, forced.invocation.id, review_session_id=session.id)

        zero_call = create_invocation(
            conn,
            source_id=source.id,
            recipe_version_ids=recipe_ids,
            force_rerun=True,
            retention="full",
            execution_build="inspection-zero-call-test",
        )
        for member in zero_call.members:
            now = datetime.now(UTC)
            save_result(
                conn,
                member_id=member.id,
                terminal=TerminalResult(
                    "preflight_failed",
                    now,
                    now,
                    error_code="credentials",
                    error_message="fixture preflight failure",
                ),
                attempts=(),
            )
        complete_invocation(conn, zero_call.id)
        zero_output = render_comparison(conn, zero_call.id)
        assert "generation calls 0; generation cost not incurred" in zero_output
        assert "Current invocation: 0 new calls; new cost not incurred" in zero_output

        with monkeypatch.context() as patch:
            patch.setattr("altiscope.store.recipes.CONFIGURATION_FORMAT_VERSION", 999)
            historical = render_comparison(conn, cached.invocation.id)
            assert str(assessment.id) in historical
            assert str(target.id) in historical

    runner = CliRunner()
    shown = runner.invoke(app, ["show-comparison", str(cached.invocation.id), "--verbose"])
    assert shown.exit_code == 0, shown.output
    assert "Exact prepared source text:" in shown.output
    assert "Frozen recipe config:" in shown.output
    assert "Source ambiguity." not in shown.output
    shown_revealed = runner.invoke(
        app,
        ["show-comparison", str(cached.invocation.id), "--review-session", str(session.id)],
    )
    assert shown_revealed.exit_code == 0, shown_revealed.output
    assert "Source ambiguity." in shown_revealed.output


def test_aggregate_inspection_shows_exact_inputs_baseline_and_failure(
    database: str, snapshot: PullRequestSnapshot
) -> None:
    with psycopg.connect(database) as conn:
        _, stored, context = _freeze_pr(conn, snapshot)
        registry = fixture_registry()
        pr_prompt = load_prompt(REPO_ROOT / "prompts/pr_summary/v3.md")
        generated = generate_account(
            context,
            FixtureProvider(['{"review":"Saved input report."}']),
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
        repository_id = conn.execute(
            "SELECT repository_id FROM pull_requests WHERE id=%s", (stored.id,)
        ).fetchone()
        assert repository_id is not None
        inputs = (load_pr_input(conn, report_id),)
        source = freeze_aggregate_source(
            conn,
            repository_id=int(repository_id[0]),
            inputs=inputs,
            query={"since": "2026-06-01", "until": "2026-06-30"},
            altitude="manager",
            prepared_text=render_inputs("Summarize for a manager.", inputs),
            preparation_contract={"renderer": "aggregate-inputs-v1"},
        )
        first, second = _recipes(conn, stage="aggregate")
        registry.models["fixture-other"] = registry.models["fixture"].model_copy(
            update={
                "id": "fixture-other",
                "model_name": "fixture-other",
                "underlying_model_id": "fixture/other-v1",
                "underlying_model_evidence": "test fixture",
            }
        )
        model_changed = create_recipe(
            conn,
            name="inspection-other-" + source.id.hex,
            registry_key="fixture-other",
            prompt=load_prompt(REPO_ROOT / "prompts/aggregate/v4.md"),
            registry=registry,
        )
        baseline = register_primary_baseline(
            conn,
            recipe_version_id=first.id,
            prompt=load_prompt(REPO_ROOT / "prompts/baseline/aggregate-v1.md"),
        )
        register_primary_baseline(
            conn,
            recipe_version_id=second.id,
            prompt=load_prompt(REPO_ROOT / "prompts/baseline/aggregate-v1.md"),
        )
        register_primary_baseline(
            conn,
            recipe_version_id=model_changed.id,
            prompt=load_prompt(REPO_ROOT / "prompts/baseline/aggregate-v1.md"),
        )
        run = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=(first.id, second.id, model_changed.id),
            retention="full",
            execution_build="aggregate-inspection-test",
            include_primary_baselines=True,
            provider_factory=lambda recipe: FixtureProvider(
                ["{}", "{}"] if recipe.id == second.id else [good_output().model_dump_json()]
            ),
        )
        output = render_comparison(conn, run.invocation.id, verbose=True)
        assert "Altitude: manager" in output
        assert f"altiscope show-report {report_id}" in output
        assert inputs[0].pr_urls[0] in output
        assert "primary_baseline" in output
        assert "model_comparison" in output
        assert str(baseline.recipe.id) in output
        assert f"Baseline for: {first.id}, {second.id}" in output or (
            f"Baseline for: {second.id}, {first.id}" in output
        )
        assert "invalid_output" in output
        assert "Failure invalid_output" in output
        assert "Assessments: not run" in output
        assert good_output().headline in output
