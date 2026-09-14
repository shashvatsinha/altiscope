from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import psycopg
import pytest
from typer.testing import CliRunner

from altiscope.assessment import run_assessment
from altiscope.cli.main import app
from altiscope.comparison.service import run_comparison
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.review import render_frozen_source, render_review_result
from altiscope.review.workflow import assessment_observation_state, retain_protocol_artifacts
from altiscope.store.comparisons import list_assessments, load_result
from altiscope.store.evaluation import (
    EffortMeasure,
    ReviewRevisionInput,
    append_review_revision,
    create_review_session,
    export_review_record,
    get_preparation,
    list_review_sessions,
    record_exposure,
    record_post_assessment_observation,
    save_preparation,
)
from tests.conftest import REPO_ROOT
from tests.test_assessment_service import (  # pyright: ignore[reportPrivateUsage]
    RecordingFixture,
    TerminalFixture,
    _assessor,  # pyright: ignore[reportPrivateUsage]
    _pr_target,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres"),
]


def _new_session(
    conn: psycopg.Connection,
    *,
    result_id: UUID,
    exposure: str = "none_declared",
):
    artifacts = retain_protocol_artifacts(conn, evaluation_dir=REPO_ROOT / "docs/evaluation")
    return create_review_session(
        conn,
        result_id=result_id,
        reviewer_id="reviewer-t1",
        protocol_artifact_id=artifacts.protocol_id,
        dataset_artifact_id=artifacts.dataset_id,
        record_contract_artifact_id=artifacts.record_contract_id,
        case_id="m3-dev-pr-test",
        case_kind="pr",
        case_group="development",
        reader_role="ic",
        familiarity_level="domain",
        familiarity_basis="Python review experience plus recorded preparation",
        declared_prior_exposure=exposure,  # type: ignore[arg-type]
        result_presentation_ordinal=1,
        started_at=datetime.now(UTC),
    )


def _initial(conn: psycopg.Connection, session_id: UUID, *, blind: str = "confirmed_unexposed"):
    return append_review_revision(
        conn,
        review_session_id=session_id,
        revision=ReviewRevisionInput(
            kind="initial_blind",
            blind_status=blind,  # type: ignore[arg-type]
            correctness_label="correct",
            correctness_rationale="The account matches the exact frozen source.",
            usefulness_status="measured",
            usefulness_score=4,
            usefulness_rationale="Useful with minor contextual qualification.",
            effort=(
                EffortMeasure(
                    component="reading",
                    status="unavailable",
                    unavailable_reason="not_collected",
                ),
                EffortMeasure(component="checking", status="measured", value=0, method="timer"),
                EffortMeasure(component="correction", status="not_applicable"),
            ),
            created_at=datetime.now(UTC),
        ),
    )


def test_guided_review_preserves_initial_revision_and_exports_all_measures(
    database: str, snapshot: PullRequestSnapshot
):
    with psycopg.connect(database) as conn:
        source, _, target = _pr_target(conn, snapshot)
        assessor = _assessor(conn)
        assessment = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=assessor.id,
            retention="full",
            provider_factory=lambda _: RecordingFixture(
                ['{"verdict":"disagree","rationale":"A material boundary may be missing."}']
            ),
        ).assessment
        session = _new_session(conn, result_id=target.id)
        preparation_id = save_preparation(
            conn,
            source_id=source.id,
            reviewer_id="reviewer-t1",
            case_id="m3-dev-pr-test",
            effort=EffortMeasure(
                component="preparation", status="measured", value=0, method="timer"
            ),
        )
        assert get_preparation(
            conn,
            source_id=source.id,
            reviewer_id="reviewer-t1",
            case_id="m3-dev-pr-test",
        ) == (
            preparation_id,
            EffortMeasure(component="preparation", status="measured", value=0, method="timer"),
        )

        with pytest.raises(ValueError, match="committed initial"):
            record_exposure(
                conn,
                review_session_id=session.id,
                assessment_id=assessment.id,
                kind="guided_reveal",
                presentation_ordinal=1,
                occurred_at=datetime.now(UTC),
            )
        initial_id = _initial(conn, session.id)
        exposure_id = record_exposure(
            conn,
            review_session_id=session.id,
            assessment_id=assessment.id,
            kind="guided_reveal",
            presentation_ordinal=1,
            occurred_at=datetime.now(UTC),
        )
        revised_id = append_review_revision(
            conn,
            review_session_id=session.id,
            revision=ReviewRevisionInput(
                kind="post_assessment",
                blind_status="known_exposed",
                correctness_label="incorrect",
                correctness_rationale="The revealed issue is material.",
                correction="Corrected exact-result account.",
                usefulness_status="measured",
                usefulness_score=3,
                usefulness_rationale="Useful after a material correction.",
                effort=(
                    EffortMeasure(
                        component="correction", status="measured", value=25, method="timer"
                    ),
                ),
                created_at=datetime.now(UTC),
            ),
            exposure_ids_seen=(exposure_id,),
        )
        record_post_assessment_observation(
            conn,
            review_session_id=session.id,
            exposure_id=exposure_id,
            assessment_id=assessment.id,
            assessment_status="succeeded",
            assessment_verdict="disagree",
            rationale="The assessment caused discovery of the material boundary.",
            assessment_related_effort=EffortMeasure(
                component="assessment_related", status="measured", value=0, method="timer"
            ),
            post_usefulness_status="measured",
            post_usefulness_score=3,
            post_usefulness_rationale="Useful after correction.",
            true_problem_detection=True,
            false_alarm=False,
            missed_problem=False,
            inconclusive=False,
            resulting_revision_id=revised_id,
        )

        record = export_review_record(conn, session.id)
        revisions = cast(list[dict[str, object]], record["revisions"])
        assert [item["revision_id"] for item in revisions] == [str(initial_id), str(revised_id)]
        first_correctness = cast(dict[str, object], revisions[0]["correctness"])
        second_correctness = cast(dict[str, object], revisions[1]["correctness"])
        first_effort = cast(dict[str, dict[str, object]], revisions[0]["effort"])
        assert first_correctness["label"] == "correct"
        assert second_correctness["label"] == "incorrect"
        assert first_effort["reading"]["status"] == "unavailable"
        assert first_effort["checking"]["value"] == 0
        preparation = cast(dict[str, dict[str, object]], record["preparation"])
        assert preparation["effort"]["value"] == 0
        observations = cast(list[dict[str, object]], record["post_assessment_observations"])
        assessment_effort = cast(dict[str, object], observations[0]["assessment_related_effort"])
        post_usefulness = cast(dict[str, object], observations[0]["post_usefulness"])
        assert assessment_effort["value"] == 0
        assert post_usefulness["score"] == 3
        assert record["result_id"] == str(target.id)
        assert load_result(conn, target.id).output == {"review": "Exact saved target output."}
        assert list_review_sessions(conn, result_id=target.id)[0].result_id == target.id
        case = cast(dict[str, object], record["case"])
        assert snapshot.number == case["pull_request_number"]

        source_text = render_frozen_source(source)
        assert source.prepared_text in source_text
        assert "/pull/42" in source_text
        assert str(target.id) in render_review_result(target)


def test_prior_exposure_and_assessment_availability_states(
    database: str, snapshot: PullRequestSnapshot
):
    with psycopg.connect(database) as conn:
        _, _, target = _pr_target(conn, snapshot)
        assessor = _assessor(conn)
        failed = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=assessor.id,
            retention="hashes_only",
            provider_factory=lambda _: TerminalFixture("refusal"),
        ).assessment
        inconclusive = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=assessor.id,
            retention="hashes_only",
            provider_factory=lambda _: RecordingFixture(
                ['{"verdict":"inconclusive","rationale":"The saved evidence is ambiguous."}']
            ),
        ).assessment
        assert assessment_observation_state(failed.status) == "failed"
        assert assessment_observation_state(inconclusive.status) == "inconclusive"
        assert {item.status for item in list_assessments(conn, target_result_id=target.id)} == {
            "refused",
            "inconclusive",
        }

        unexposed = _new_session(conn, result_id=target.id)
        _initial(conn, unexposed.id)
        record = export_review_record(conn, unexposed.id)
        assert record["assessment_availability"] == "recorded"
        history = cast(list[dict[str, object]], record["assessment_history"])
        assert all(not item["exposed"] for item in history)
        assert all(item["verdict"] is None for item in history)

        prior = _new_session(conn, result_id=target.id, exposure="known")
        prior_exposure = record_exposure(
            conn,
            review_session_id=prior.id,
            assessment_id=inconclusive.id,
            kind="declared_prior_external",
            presentation_ordinal=1,
            occurred_at=datetime.now(UTC),
        )
        with pytest.raises(ValueError, match="confirmed-unexposed"):
            _initial(conn, prior.id)
        append_review_revision(
            conn,
            review_session_id=prior.id,
            revision=ReviewRevisionInput(
                kind="initial_blind",
                blind_status="known_exposed",
                correctness_label="unclear",
                correctness_rationale="Prior exposure prevents a blind classification.",
                usefulness_status="unavailable",
                effort=(EffortMeasure(component="correction", status="not_applicable"),),
                created_at=datetime.now(UTC),
            ),
            exposure_ids_seen=(prior_exposure,),
        )
        prior_record = export_review_record(conn, prior.id)
        prior_history = cast(list[dict[str, object]], prior_record["assessment_history"])
        exposed = [item for item in prior_history if item["exposed"]]
        assert exposed[0]["verdict"] == "inconclusive"


def test_no_assessment_is_exported_as_not_run(database: str, snapshot: PullRequestSnapshot):
    with psycopg.connect(database) as conn:
        _, _, target = _pr_target(conn, snapshot)
        session = _new_session(conn, result_id=target.id)
        _initial(conn, session.id)
        record = export_review_record(conn, session.id)
        assert record["assessment_availability"] == "not_run"
        assert record["assessment_history"] == []


def test_reviews_keep_exact_identity_across_cache_reuse_and_forced_rerun(
    database: str, snapshot: PullRequestSnapshot
):
    with psycopg.connect(database) as conn:
        source, _, target = _pr_target(conn, snapshot)
        recipe_rows = conn.execute(
            "SELECT m2.recipe_version_id FROM comparison_run_results r "
            "JOIN comparison_members m1 ON m1.id=r.origin_member_id "
            "JOIN comparison_members m2 ON m2.invocation_id=m1.invocation_id "
            "WHERE r.id=%s ORDER BY m2.ordinal",
            (target.id,),
        ).fetchall()
        recipe_ids = tuple(UUID(str(row[0])) for row in recipe_rows)
        reused = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=recipe_ids,
            retention="full",
            execution_build="review-reuse-test",
            include_primary_baselines=False,
        )
        assert reused.members[0].disposition == "reused"
        assert reused.members[0].result.id == target.id
        forced = run_comparison(
            conn,
            source_id=source.id,
            recipe_version_ids=recipe_ids,
            retention="full",
            execution_build="review-rerun-test",
            regenerate=True,
            include_primary_baselines=False,
            provider_factory=lambda _: RecordingFixture(
                ['{"review":"A separately frozen forced-rerun output."}']
            ),
        )
        rerun_result = forced.members[0].result
        assert rerun_result.id != target.id
        reused_session = _new_session(conn, result_id=reused.members[0].result.id)
        rerun_session = _new_session(conn, result_id=rerun_result.id)
        assert reused_session.result_id == target.id
        assert rerun_session.result_id == rerun_result.id
        assert reused_session.source_id == rerun_session.source_id == source.id


def test_cli_commits_initial_judgment_before_revealing_assessment(
    database: str, snapshot: PullRequestSnapshot, monkeypatch: pytest.MonkeyPatch
):
    with psycopg.connect(database) as conn:
        _, _, target = _pr_target(conn, snapshot)
        assessor = _assessor(conn)
        assessment = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=assessor.id,
            retention="full",
            provider_factory=lambda _: RecordingFixture(
                ['{"verdict":"agree","rationale":"SECRET ASSESSMENT RATIONALE"}']
            ),
        ).assessment

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("ALTISCOPE_DATABASE_URL", database)
    guided_input = "\n0\n\n\n0\n\n\n0\n\n\n\n\n\n4\nUseful for the assigned reader.\n"
    started = CliRunner().invoke(
        app,
        [
            "comparisons",
            "review",
            str(target.id),
            "--reviewer",
            "reviewer-cli",
            "--case-id",
            "m3-dev-pr-cli",
            "--familiarity-basis",
            "Python review experience",
        ],
        input=guided_input,
    )
    assert started.exit_code == 0, started.output
    assert "Initial judgment committed" in started.output
    assert "SECRET ASSESSMENT RATIONALE" not in started.output
    marker = "Review session "
    session_id = started.output.split(marker, 1)[1].split(";", 1)[0]

    revealed = CliRunner().invoke(app, ["reviews", "reveal", session_id, str(assessment.id)])
    assert revealed.exit_code == 0, revealed.output
    assert revealed.output.index("Exposure ") < revealed.output.index("SECRET ASSESSMENT RATIONALE")
