from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import psycopg
import pytest

from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.prompts import load_prompt
from altiscope.store.comparisons import (
    TerminalResult,
    create_invocation,
    find_comparison_result,
    freeze_aggregate_source,
    freeze_pr_source,
    load_result,
    load_source,
    reuse_result,
    save_result,
)
from altiscope.store.evaluation import (
    EffortMeasure,
    ReviewRevisionInput,
    append_review_revision,
    create_review_session,
    save_evaluation_artifact,
)
from altiscope.store.recipes import RecipeOverrides, create_recipe
from tests.conftest import REPO_ROOT

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres"),
]


def _setup_comparison(
    conn: psycopg.Connection,
    snapshot: PullRequestSnapshot,
    retention: Literal["full", "hashes_only"],
):
    from altiscope.store.snapshots import save_snapshot
    from altiscope.summarize.context import render_user_prompt
    from altiscope.summarize.fixture import FixtureProvider, fixture_registry
    from altiscope.summarize.generate import generate_account
    from altiscope.summarize.service import prepare

    suffix = uuid4().hex[:12]
    snapshot = snapshot.model_copy(
        update={
            "repository": f"acme/widgets-{suffix}",
            "html_url": f"https://github.com/acme/widgets-{suffix}/pull/42",
        }
    )
    stored = save_snapshot(
        conn,
        snapshot,
        repository_id=700_000_000 + int(uuid4().hex[:6], 16),
        default_branch="main",
        raw={"comparison": True},
    )
    context = prepare(snapshot)
    prepared_text = render_user_prompt(context)
    source = freeze_pr_source(
        conn,
        snapshot_id=stored.id,
        preparation_document={
            "facts": context.facts.model_dump(mode="json"),
            "manifest": context.manifest.model_dump(mode="json"),
        },
        prepared_text=prepared_text,
        preparation_contract={"renderer": "pr-context-v1", "facts": "v1", "policy": "v1"},
    )
    registry = fixture_registry()
    prompt = load_prompt(REPO_ROOT / "prompts" / "pr_summary" / "v3.md")
    name = "comparison-" + uuid4().hex
    first = create_recipe(
        conn,
        name=name,
        registry_key="fixture",
        prompt=prompt,
        registry=registry,
        overrides=RecipeOverrides(effort="low", reserved_output_tokens=4096),
    )
    second = create_recipe(
        conn,
        name=name,
        registry_key="fixture",
        prompt=prompt,
        registry=registry,
        overrides=RecipeOverrides(effort="high", reserved_output_tokens=4096),
    )
    invocation = create_invocation(
        conn,
        source_id=source.id,
        recipe_version_ids=(first.id, second.id),
        force_rerun=False,
        retention=retention,
        execution_build="test-build",
    )
    generated = generate_account(
        context,
        FixtureProvider(['{"review":"Frozen comparison output."}']),
        first.config.to_registry().models["fixture"],
        system=first.prompt.body,
        max_tokens=first.config.generation.reserved_output_tokens,
        effort=first.config.generation.requested_effort,
        input_budget=first.config.budget.input_limit,
    )
    assert generated.publication.output is not None
    now = datetime.now(UTC)
    result = save_result(
        conn,
        member_id=invocation.members[0].id,
        terminal=TerminalResult(
            status="succeeded",
            output=generated.publication.output,
            started_at=now,
            finished_at=now,
        ),
        attempts=generated.attempts,
    )
    return source, first, second, invocation, generated, result


@pytest.mark.parametrize("retention", ["full", "hashes_only"])
def test_results_round_trip_with_attempts_failures_and_reuse(
    database: str, snapshot: PullRequestSnapshot, retention: Literal["full", "hashes_only"]
):
    import psycopg

    with psycopg.connect(database) as conn:
        source, first, second, invocation, _, result = _setup_comparison(conn, snapshot, retention)
        loaded = load_result(conn, result.id)
        assert loaded.output == {"review": "Frozen comparison output."}
        assert len(loaded.call_ids) == 1
        payloads = conn.execute(
            "SELECT request_payload,response_text,selected_config,usage_status,cost_status "
            "FROM llm_calls WHERE id=%s",
            (loaded.call_ids[0],),
        ).fetchone()
        assert payloads is not None
        assert (payloads[0] is None) == (retention == "hashes_only")
        assert (payloads[1] is None) == (retention == "hashes_only")
        assert payloads[2]["model"]["wire_name"] == "fixture"
        assert payloads[3:] == ("unavailable", "unavailable")

        failed = save_result(
            conn,
            member_id=invocation.members[1].id,
            terminal=TerminalResult(
                status="preflight_failed",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                error_code="oversized_input",
                error_message="request exceeds the frozen recipe budget",
            ),
            attempts=(),
        )
        assert failed.call_ids == () and failed.output is None
        assert conn.execute(
            "SELECT current_call_count,current_cost_usd,current_cost_status "
            "FROM comparison_members WHERE id=%s",
            (invocation.members[1].id,),
        ).fetchone() == (0, None, "not_incurred")

        cached = find_comparison_result(conn, source_id=source.id, recipe_version_id=first.id)
        assert cached is not None and cached.id == result.id
        later = create_invocation(
            conn,
            source_id=source.id,
            recipe_version_ids=(first.id, second.id),
            force_rerun=False,
            retention="full",
            execution_build="later-build",
        )
        reused = reuse_result(conn, member_id=later.members[0].id, result_id=result.id)
        assert reused.id == result.id
        membership = conn.execute(
            "SELECT disposition,current_call_count,current_cost_status "
            "FROM comparison_members WHERE id=%s",
            (later.members[0].id,),
        ).fetchone()
        assert membership == ("reused", 0, "not_incurred")


def test_result_and_attempt_group_rolls_back_atomically(
    database: str, snapshot: PullRequestSnapshot
):
    import psycopg

    with psycopg.connect(database) as conn:
        _, _, _, invocation, generated, _ = _setup_comparison(conn, snapshot, "full")
        later = create_invocation(
            conn,
            source_id=invocation.source_id,
            recipe_version_ids=tuple(member.recipe_version_id for member in invocation.members),
            force_rerun=True,
            retention="full",
            execution_build="rollback-test",
        )
        assert generated.publication.output is not None
        now = datetime.now(UTC)
        repeated = generated.attempts + generated.attempts + generated.attempts
        with pytest.raises(psycopg.errors.CheckViolation):
            save_result(
                conn,
                member_id=later.members[0].id,
                terminal=TerminalResult(
                    status="succeeded",
                    output=generated.publication.output,
                    started_at=now,
                    finished_at=now,
                ),
                attempts=repeated,
            )
        member = conn.execute(
            "SELECT disposition,result_id FROM comparison_members WHERE id=%s",
            (later.members[0].id,),
        ).fetchone()
        assert member == ("pending", None)
        assert conn.execute(
            "SELECT count(*) FROM comparison_run_results WHERE origin_member_id=%s",
            (later.members[0].id,),
        ).fetchone() == (0,)


def test_review_record_targets_exact_result_and_preserves_initial_revision(
    database: str, snapshot: PullRequestSnapshot
):
    import psycopg

    with psycopg.connect(database) as conn:
        source, _, _, invocation, _, result = _setup_comparison(conn, snapshot, "hashes_only")
        protocol = save_evaluation_artifact(
            conn,
            kind="protocol",
            external_id="m3-evaluation-v1",
            version="1",
            content={"text": "retained protocol content"},
        )
        contract = save_evaluation_artifact(
            conn,
            kind="record_contract",
            external_id="m3-review-record-v1",
            version="1",
            content={"schema": "retained review record contract"},
        )
        session = create_review_session(
            conn,
            result_id=result.id,
            reviewer_id="reviewer-t1",
            protocol_artifact_id=protocol,
            record_contract_artifact_id=contract,
            case_id="development-example",
            case_kind="pr",
            case_group="development",
            reader_role="ic",
            familiarity_level="domain",
            familiarity_basis="prepared Python reviewer",
            declared_prior_exposure="none_declared",
            result_presentation_ordinal=1,
            started_at=datetime.now(UTC),
            invocation_id=invocation.id,
        )
        revision_id = append_review_revision(
            conn,
            review_session_id=session.id,
            revision=ReviewRevisionInput(
                kind="initial_blind",
                blind_status="confirmed_unexposed",
                correctness_label="correct",
                correctness_rationale="The account matches the frozen source.",
                usefulness_status="measured",
                usefulness_score=4,
                usefulness_rationale="Useful with a small amount of context.",
                effort=(
                    EffortMeasure(
                        component="reading", status="measured", value=1000, method="timer"
                    ),
                    EffortMeasure(
                        component="checking", status="measured", value=2000, method="timer"
                    ),
                ),
                created_at=datetime.now(UTC),
            ),
        )
        row = conn.execute(
            "SELECT review_session_id,correctness_label,blind_status FROM review_revisions "
            "WHERE id=%s",
            (revision_id,),
        ).fetchone()
        assert row == (session.id, "correct", "confirmed_unexposed")
        assert session.source_id == source.id


def test_aggregate_source_round_trip_retains_underlying_pr_links(
    database: str, snapshot: PullRequestSnapshot
):
    from altiscope.aggregate.inputs import render_inputs
    from altiscope.llm.router import route
    from altiscope.store.accounts import save_account
    from altiscope.store.aggregates import load_pr_input
    from altiscope.store.snapshots import save_snapshot
    from altiscope.summarize.context import render_user_prompt
    from altiscope.summarize.fixture import FixtureProvider, fixture_registry
    from altiscope.summarize.generate import generate_account, request_tokens
    from altiscope.summarize.service import prepare

    with psycopg.connect(database) as conn:
        suffix = uuid4().hex[:12]
        frozen_snapshot = snapshot.model_copy(
            update={
                "repository": f"acme/aggregate-links-{suffix}",
                "html_url": f"https://github.com/acme/aggregate-links-{suffix}/pull/42",
            }
        )
        repository_github_id = 800_000_000 + int(uuid4().hex[:6], 16)
        stored = save_snapshot(
            conn,
            frozen_snapshot,
            repository_id=repository_github_id,
            default_branch="main",
            raw={"aggregate_links": True},
        )
        repository_row = conn.execute(
            "SELECT id FROM repositories WHERE github_id=%s", (repository_github_id,)
        ).fetchone()
        assert repository_row is not None
        repository_id = int(repository_row[0])
        context = prepare(frozen_snapshot)
        registry = fixture_registry()
        prompt = load_prompt(REPO_ROOT / "prompts" / "pr_summary" / "v3.md")
        generated = generate_account(
            context,
            FixtureProvider(['{"review":"Saved source report."}']),
            registry.models["fixture"],
            system=prompt.body,
            max_tokens=4096,
            effort="low",
            input_budget=100_000,
        )
        decision = route(
            registry,
            "pr_summary",
            request_tokens(prompt.body, render_user_prompt(context)),
        )
        report_id = save_account(
            conn,
            stored.id,
            context,
            generated=generated,
            prompt=prompt,
            decision=decision,
            registry=registry,
            retention="full",
        )
        report_input = load_pr_input(conn, report_id)
        source = freeze_aggregate_source(
            conn,
            repository_id=repository_id,
            inputs=(report_input,),
            query={"window": "test"},
            altitude="manager",
            prepared_text=render_inputs("Compose", (report_input,)),
            preparation_contract={"renderer": "aggregate-test-v1"},
        )
        loaded = load_source(conn, source.id)
        assert loaded.inputs[0].pr_urls == report_input.pr_urls
        assert loaded.inputs[0].pr_urls == (frozen_snapshot.html_url,)
