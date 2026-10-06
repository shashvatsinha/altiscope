"""Persist a credential-free PR and aggregate comparison with a simulated review.

All responses and judgments in this file are hand-authored workflow fixtures. They
are never evidence of model quality or real human evaluation.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from altiscope.aggregate.inputs import render_inputs
from altiscope.assessment import run_assessment
from altiscope.comparison.service import run_comparison
from altiscope.config import load_settings
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.llm.registry import Registry
from altiscope.llm.router import route
from altiscope.prompts import load_prompt
from altiscope.review.workflow import retain_protocol_artifacts
from altiscope.store.accounts import save_account
from altiscope.store.aggregates import load_pr_input
from altiscope.store.baselines import register_primary_baseline
from altiscope.store.comparisons import freeze_aggregate_source, freeze_pr_source
from altiscope.store.db import connect
from altiscope.store.evaluation import (
    EffortMeasure,
    ReviewRevisionInput,
    append_review_revision,
    complete_review_session,
    create_review_session,
    export_review_record,
    record_exposure,
    record_post_assessment_observation,
    save_preparation,
)
from altiscope.store.recipes import create_recipe
from altiscope.store.snapshots import load_snapshot, save_snapshot
from altiscope.summarize.context import render_user_prompt
from altiscope.summarize.fixture import FixtureProvider, fixture_registry
from altiscope.summarize.generate import generate_account, request_tokens
from altiscope.summarize.service import prepare


def _registry() -> Registry:
    registry = fixture_registry()
    for key, identity in (
        ("fixture-a", "synthetic/generator-a-v1"),
        ("fixture-b", "synthetic/generator-b-v1"),
        ("fixture-assessor", "synthetic/assessor-v1"),
    ):
        registry.models[key] = registry.models["fixture"].model_copy(
            update={
                "id": key,
                "model_name": "fixture",
                "underlying_model_id": identity,
                "underlying_model_evidence": "distinct hand-authored fixture identity",
                "model_version_kind": "versioned",
            }
        )
    return registry


def _response(stage: str, name: str, *, pilot: bool) -> str:
    baseline = "baseline" in name
    second = "candidate-b" in name
    if stage == "pr_summary":
        if pilot:
            review = (
                "Text-like file decoding now detects every HTML page's character set."
                if second and not baseline
                else "The PR changes text-like file decoding and adds a Shift JIS CSV test."
            )
            return json.dumps({"review": review})
        review = (
            "The change makes run() thread-safe and a test proves concurrent safety."
            if second and not baseline
            else "run() now uses a lock; a test exercises the changed function."
            if not baseline
            else "This PR changes run() and adds a test."
        )
        return json.dumps({"review": review})
    if pilot:
        narrative = "The supplied report describes text-like file decoding and a CSV test."
        return json.dumps(
            {
                "headline": "Text decoding update",
                "sections": [{"heading": "Changed behavior", "text": narrative}],
                "narrative": narrative,
            }
        )
    headline = "Thread safety update" if not baseline else "Repository update"
    narrative = (
        "A lock now wraps run(); the supplied PR report describes a basic test."
        if not second
        else "The supplied PR report describes a lock and a test for run()."
    )
    return json.dumps(
        {
            "headline": headline,
            "sections": [{"heading": "Changed behavior", "text": narrative}],
            "narrative": narrative,
        }
    )


def main() -> None:  # noqa: PLR0915
    if len(sys.argv) > 2 or (len(sys.argv) == 2 and sys.argv[1] != "--pilot-pr19"):
        raise SystemExit("usage: synthetic_study.py [--pilot-pr19]")
    pilot = len(sys.argv) == 2
    settings = load_settings()
    root = settings.prompts_dir.parent
    suffix = uuid4().hex[:8]
    registry = _registry()
    with connect(settings.database_url) as conn:
        if pilot:
            stored = load_snapshot(conn, "microsoft/markitdown", 19)
            snapshot = stored.snapshot
        else:
            snapshot = PullRequestSnapshot.model_validate_json(
                (root / "examples/m1/snapshot.json").read_text()
            ).model_copy(
                update={
                    "repository": f"acme/m3-synthetic-{suffix}",
                    "html_url": f"https://github.com/acme/m3-synthetic-{suffix}/pull/42",
                }
            )
            stored = save_snapshot(
                conn,
                snapshot,
                repository_id=950_000_000 + int(suffix[:6], 16),
                default_branch="main",
                raw={"example": "m3-synthetic-study"},
            )
        context = prepare(snapshot)
        prepared = render_user_prompt(context)
        pr_source = freeze_pr_source(
            conn,
            snapshot_id=stored.id,
            preparation_document={
                "facts": context.facts.model_dump(mode="json"),
                "manifest": context.manifest.model_dump(mode="json"),
            },
            prepared_text=prepared,
            preparation_contract={"renderer": "pr-context-v1", "facts": "v1", "policy": "v1"},
        )
        pr_prompt = load_prompt(root / "prompts/pr_summary/v3.md")
        pr_recipes = tuple(
            create_recipe(
                conn,
                name=f"synthetic-{suffix}-pr-candidate-{letter}",
                registry_key=f"fixture-{letter}",
                prompt=pr_prompt,
                registry=registry,
            )
            for letter in ("a", "b")
        )
        for recipe in pr_recipes:
            register_primary_baseline(
                conn,
                recipe_version_id=recipe.id,
                prompt=load_prompt(root / "prompts/baseline/pr_summary-v1.md"),
            )
        pr_run = run_comparison(
            conn,
            source_id=pr_source.id,
            recipe_version_ids=tuple(recipe.id for recipe in pr_recipes),
            retention="full",
            execution_build="synthetic-study-v1",
            provider_factory=lambda recipe: FixtureProvider(
                [_response("pr_summary", recipe.name, pilot=pilot)]
            ),
        )

        # The aggregate consumes one exact saved production-style report version.
        generated = generate_account(
            context,
            FixtureProvider(
                [
                    json.dumps(
                        {
                            "review": (
                                "The PR changes text-like decoding and adds a Shift JIS CSV test."
                                if pilot
                                else "run() now uses a lock, and a test calls the function."
                            )
                        }
                    )
                ]
            ),
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
            decision=route(registry, "pr_summary", request_tokens(pr_prompt.body, prepared)),
            registry=registry,
            retention="full",
        )
        inputs = (load_pr_input(conn, report_id),)
        aggregate_source = freeze_aggregate_source(
            conn,
            repository_id=pr_source.repository_id,
            inputs=inputs,
            query={"example": "synthetic manager summary"},
            altitude="manager",
            prepared_text=render_inputs("Summarize the supplied work for a manager.", inputs),
            preparation_contract={"renderer": "aggregate-inputs-v1"},
        )
        aggregate_prompt = load_prompt(root / "prompts/aggregate/v4.md")
        aggregate_recipes = tuple(
            create_recipe(
                conn,
                name=f"synthetic-{suffix}-aggregate-candidate-{letter}",
                registry_key=f"fixture-{letter}",
                prompt=aggregate_prompt,
                registry=registry,
            )
            for letter in ("a", "b")
        )
        for recipe in aggregate_recipes:
            register_primary_baseline(
                conn,
                recipe_version_id=recipe.id,
                prompt=load_prompt(root / "prompts/baseline/aggregate-v1.md"),
            )
        aggregate_run = run_comparison(
            conn,
            source_id=aggregate_source.id,
            recipe_version_ids=tuple(recipe.id for recipe in aggregate_recipes),
            retention="full",
            execution_build="synthetic-study-v1",
            provider_factory=lambda recipe: FixtureProvider(
                [_response("aggregate", recipe.name, pilot=pilot)]
            ),
        )

        assessor = create_recipe(
            conn,
            name=f"synthetic-{suffix}-assessor",
            registry_key="fixture-assessor",
            prompt=load_prompt(root / "prompts/verify/v2.md"),
            registry=registry,
        )
        target = pr_run.members[1].result
        assessment = run_assessment(
            conn,
            target_result_id=target.id,
            assessor_recipe_version_id=assessor.id,
            retention="full",
            provider_factory=lambda _: FixtureProvider(
                [
                    json.dumps(
                        {
                            "verdict": "disagree",
                            "rationale": (
                                "The PR says HTML charset detection is unsupported."
                                if pilot
                                else "The saved test makes one call; concurrency is untested."
                            ),
                        }
                    )
                ]
            ),
        ).assessment

        # This simulated review checks revision and exposure persistence only.
        artifacts = retain_protocol_artifacts(conn, evaluation_dir=root / "docs/evaluation")
        session = create_review_session(
            conn,
            result_id=target.id,
            reviewer_id="synthetic-reviewer-fixture",
            protocol_artifact_id=artifacts.protocol_id,
            dataset_artifact_id=artifacts.dataset_id,
            record_contract_artifact_id=artifacts.record_contract_id,
            case_id="m3-dev-pr-001" if pilot else "synthetic-pr-42",
            case_kind="pr",
            case_group="development",
            reader_role="ic",
            familiarity_level="domain",
            familiarity_basis="Simulated fixture; no human reviewer participated",
            declared_prior_exposure="none_declared",
            result_presentation_ordinal=1,
            started_at=datetime.now(UTC),
        )
        save_preparation(
            conn,
            source_id=pr_source.id,
            reviewer_id="synthetic-reviewer-fixture",
            case_id="m3-dev-pr-001" if pilot else "synthetic-pr-42",
            effort=EffortMeasure(
                component="preparation", status="unavailable", unavailable_reason="not_collected"
            ),
        )
        initial = ReviewRevisionInput(
            kind="initial_blind",
            blind_status="confirmed_unexposed",
            correctness_label="incorrect",
            correctness_rationale=(
                "The source explicitly excludes HTML charset detection."
                if pilot
                else "The saved test makes one call; concurrency is not exercised."
            ),
            usefulness_status="measured",
            usefulness_score=2,
            usefulness_rationale="The unsupported test claim limits its use.",
            effort=(
                EffortMeasure(
                    component="reading", status="unavailable", unavailable_reason="not_collected"
                ),
                EffortMeasure(
                    component="checking", status="unavailable", unavailable_reason="not_collected"
                ),
                EffortMeasure(component="correction", status="not_applicable"),
            ),
            created_at=datetime.now(UTC),
        )
        append_review_revision(conn, review_session_id=session.id, revision=initial)
        exposure_id = record_exposure(
            conn,
            review_session_id=session.id,
            assessment_id=assessment.id,
            kind="guided_reveal",
            presentation_ordinal=1,
            occurred_at=datetime.now(UTC),
        )
        record_post_assessment_observation(
            conn,
            review_session_id=session.id,
            exposure_id=exposure_id,
            assessment_id=assessment.id,
            assessment_status="succeeded",
            assessment_verdict="disagree",
            rationale="Fixture assessor flags the same unsupported claim.",
            assessment_related_effort=EffortMeasure(
                component="assessment_related",
                status="unavailable",
                unavailable_reason="not_collected",
            ),
            post_usefulness_status="measured",
            post_usefulness_score=2,
            post_usefulness_rationale="The account still needs correction.",
            true_problem_detection=True,
            false_alarm=False,
            missed_problem=False,
            inconclusive=False,
        )
        complete_review_session(conn, session.id, datetime.now(UTC))
        exported = export_review_record(conn, session.id)

    print(
        "HAND-AUTHORED OFFLINE PILOT; NO LIVE MODEL OR HUMAN REVIEW"
        if pilot
        else "HAND-AUTHORED SYNTHETIC DEMO; NO LIVE MODEL OR HUMAN REVIEW"
    )
    print(f"Source: {'real development PR #19' if pilot else 'synthetic PR fixture'}")
    print(f"PR source: {pr_source.id}; comparison: {pr_run.invocation.id}")
    print(f"Aggregate source: {aggregate_source.id}; comparison: {aggregate_run.invocation.id}")
    print(f"Input PR report version: {report_id}")
    print(f"Disagreement assessment: {assessment.id}; simulated review: {session.id}")
    print(f"Exported review revisions: {len(cast(list[object], exported['revisions']))}")
    print(f"Inspect: altiscope show-comparison {pr_run.invocation.id}")
    print(f"Inspect: altiscope show-comparison {aggregate_run.invocation.id}")
    print(f"Export: altiscope reviews export {session.id} --output /tmp/m3-synthetic-review.json")


if __name__ == "__main__":
    main()
