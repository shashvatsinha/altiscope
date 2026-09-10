from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import psycopg
import pytest

from altiscope.aggregate.inputs import ReportInput
from altiscope.aggregate.resolve import resolve_reports
from altiscope.aggregate.service import AggregateError, AggregateQuery, aggregate_reports
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.prompts import latest_prompt
from altiscope.schemas.aggregate import Altitude
from altiscope.store.aggregates import PostgresAggregateStore, load_pr_input
from altiscope.store.snapshots import save_snapshot
from altiscope.summarize.fixture import FixtureProvider, fixture_registry
from altiscope.summarize.service import summarize
from tests.conftest import REPO_ROOT
from tests.test_aggregate_generation import good_output
from tests.test_snapshot_store import unique_snapshot

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres"),
]


def test_persisted_versions_calls_failures_and_latest_resolution(
    database: str, snapshot: PullRequestSnapshot
):
    snapshot, repo_id = unique_snapshot(snapshot)
    registry = fixture_registry()
    pr_prompt = latest_prompt(REPO_ROOT / "prompts", "pr_summary")
    prompt = latest_prompt(REPO_ROOT / "prompts", "aggregate")
    query = AggregateQuery(
        repository=snapshot.repository,
        since=datetime(2026, 6, 1, tzinfo=UTC),
        until=datetime(2026, 6, 30, tzinfo=UTC),
        altitude=Altitude.manager,
    )
    good = good_output().model_dump_json()
    with psycopg.connect(database, autocommit=True) as conn:
        stored = save_snapshot(conn, snapshot, repository_id=repo_id, default_branch="main", raw={})

        def review(text: str):
            import json

            return summarize(
                conn,
                stored,
                registry=registry,
                prompt=pr_prompt,
                retention="full",
                provider=FixtureProvider([json.dumps({"review": text})]),
            )

        first_id = review("Added a lock.")
        inputs = resolve_reports(
            conn,
            query,
            registry=registry,
            prompt=pr_prompt,
            retention="full",
            client=None,
            provider=FixtureProvider([]),
        )
        assert inputs[0].report_version_id == str(first_id)
        store = PostgresAggregateStore(conn)

        def run(
            items: tuple[ReportInput, ...] = inputs,
            provider: FixtureProvider | None = None,
            *,
            force: bool = False,
            retention: str = "full",
        ):
            return aggregate_reports(
                items,
                query=query,
                store=store,
                registry=registry,
                prompt=prompt,
                provider=provider or FixtureProvider([good]),
                force=force,
                retention=retention,
            )

        first = run(provider=FixtureProvider(["bad", good]), retention="hashes_only").report
        assert first is not None and store.get(first.id) == first
        calls = conn.execute(
            "SELECT c.request_payload,c.response_text,c.attempt_ordinal,"
            "c.stage,c.generation_id,p.source_text "
            "FROM aggregate_report_calls a JOIN llm_calls c ON c.id=a.call_id "
            "JOIN prompt_versions p ON p.id=c.prompt_version_id "
            "WHERE a.report_id=%s ORDER BY c.id",
            (UUID(first.id),),
        ).fetchall()
        assert len(calls) == 2 and calls[0][:4] == (None, None, 1, "aggregate") and calls[1][2] == 2
        assert calls[0][4] == calls[1][4] and calls[1][5] == prompt.source_text
        assert run(provider=FixtureProvider([])).calls == 0
        second_id = review("Added a lock around the working-directory lookup.")
        latest = resolve_reports(
            conn,
            query,
            registry=registry,
            prompt=pr_prompt,
            retention="full",
            client=None,
            provider=FixtureProvider([]),
        )
        assert latest[0].report_version_id == str(second_id)
        second = run(latest).report
        assert second is not None and second.id != first.id
        assert store.get(first.id).inputs == inputs
        assert load_pr_input(conn, first_id) == inputs[0]
        with pytest.raises(AggregateError):
            run(latest, provider=FixtureProvider(["bad", "bad"]), force=True)
        assert store.find(second.input_hash) == second
        failed = conn.execute(
            "SELECT report FROM aggregate_reports WHERE input_hash=%s AND status='failed'",
            (second.input_hash,),
        ).fetchone()
        assert failed and failed[0]["errors"]
        # Changed source creates a new snapshot and new PR report, never old-source reuse.
        snapshot = snapshot.model_copy(update={"body": "Edited context"})
        stored = save_snapshot(conn, snapshot, repository_id=repo_id, default_branch="main", raw={})
        refreshed = resolve_reports(
            conn,
            query,
            registry=registry,
            prompt=pr_prompt,
            retention="full",
            client=None,
            provider=FixtureProvider(['{"review":"A source-refreshed review."}']),
        )
        third = run(refreshed).report
        assert third and third.input_hash != second.input_hash
        assert store.get(first.id) == first
        # Forged source text must not get attached to a real report ID.
        before = conn.execute("SELECT count(*) FROM aggregate_reports").fetchone()
        with pytest.raises(ValueError, match="does not match stored"):
            run((replace(refreshed[0], text="forged"),))
        assert conn.execute("SELECT count(*) FROM aggregate_reports").fetchone() == before


def test_remote_refresh_and_failed_missing_review(database: str, snapshot: PullRequestSnapshot):
    from unittest.mock import Mock

    from altiscope.ingest.github.pat import PatClient

    snapshot, repo_id = unique_snapshot(snapshot)
    registry = fixture_registry()
    query = AggregateQuery(
        repository=snapshot.repository,
        since=datetime(2026, 6, 1, tzinfo=UTC),
        until=datetime(2026, 6, 30, tzinfo=UTC),
        altitude=Altitude.ic,
    )
    client = Mock(spec=PatClient)
    client.list_merged_pull_requests.return_value = [snapshot.number]
    client.fetch_pull_request.return_value = snapshot
    client.repository_metadata = {
        "id": repo_id,
        "full_name": snapshot.repository,
        "default_branch": "main",
    }
    client.raw = {}
    prompt = latest_prompt(REPO_ROOT / "prompts", "pr_summary")
    with psycopg.connect(database, autocommit=True) as conn:

        def resolve(provider: FixtureProvider):
            return resolve_reports(
                conn,
                query,
                registry=registry,
                prompt=prompt,
                retention="full",
                client=client,
                provider=provider,
            )

        initial = resolve(FixtureProvider(['{"review":"Initial review"}']))
        # A matching remote snapshot needs no new PR model call.
        assert resolve(FixtureProvider([])) == initial
        assert client.fetch_pull_request.call_count == 2
        client.fetch_pull_request.return_value = snapshot.model_copy(
            update={"body": "New remote text"}
        )
        changed = resolve(FixtureProvider(['{"review":"Updated review"}']))
        assert changed[0].source_hash != initial[0].source_hash
        assert changed[0].report_version_id != initial[0].report_version_id
        # Remote membership is authoritative even when local snapshots exist.
        client.list_merged_pull_requests.return_value = []
        assert resolve(FixtureProvider([])) == ()
        client.list_merged_pull_requests.return_value = [snapshot.number]
        client.fetch_pull_request.return_value = snapshot.model_copy(
            update={"body": "Further remote text"}
        )
        with pytest.raises(ValueError, match="Published PR report"):
            resolve(FixtureProvider(["invalid", "invalid"]))
        assert conn.execute(
            "SELECT count(*) FROM aggregate_reports WHERE report->'query'->>'repository'=%s",
            (snapshot.repository,),
        ).fetchone() == (0,)


def test_store_rolls_back_report_edges_and_calls(database: str, snapshot: PullRequestSnapshot):
    from uuid import uuid4

    from altiscope.aggregate.generate import generate_aggregate
    from altiscope.llm.router import route

    snapshot, repo_id = unique_snapshot(snapshot)
    registry = fixture_registry()
    prompt = latest_prompt(REPO_ROOT / "prompts", "aggregate")
    query = AggregateQuery(
        repository=snapshot.repository,
        since=datetime(2026, 6, 1, tzinfo=UTC),
        until=datetime(2026, 6, 30, tzinfo=UTC),
        altitude=Altitude.manager,
    )
    with psycopg.connect(database, autocommit=True) as conn:
        stored = save_snapshot(conn, snapshot, repository_id=repo_id, default_branch="main", raw={})
        summary_id = summarize(
            conn,
            stored,
            registry=registry,
            prompt=latest_prompt(REPO_ROOT / "prompts", "pr_summary"),
            retention="full",
            provider=FixtureProvider(['{"review":"Added a lock."}']),
        )
        inputs = (load_pr_input(conn, summary_id),)
        store = PostgresAggregateStore(conn)
        result = aggregate_reports(
            inputs,
            query=query,
            store=store,
            registry=registry,
            prompt=prompt,
            provider=FixtureProvider([good_output().model_dump_json()]),
        )
        assert result.report
        generated = generate_aggregate(
            FixtureProvider([good_output().model_dump_json()]),
            registry.models["fixture"],
            system=prompt.body,
            user=query.instruction(),
            inputs=inputs,
            max_tokens=4096,
            effort="low",
            input_budget=100000,
        )
        failed_id = str(uuid4())
        with pytest.raises(ValueError, match="retention"):
            store.save(
                result.report.model_copy(update={"id": failed_id}),
                generated,
                prompt=prompt,
                decision=route(registry, "aggregate", 1000),
                registry=registry,
                retention="invalid",
            )
        assert conn.execute(
            "SELECT count(*) FROM aggregate_reports WHERE id=%s", (UUID(failed_id),)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM aggregate_report_inputs WHERE report_id=%s", (UUID(failed_id),)
        ).fetchone() == (0,)
