from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import Mock

import psycopg
import pytest

from altiscope.aggregate.inputs import ReportInput
from altiscope.aggregate.resolve import resolve_reports
from altiscope.aggregate.service import AggregateQuery, aggregate_reports
from altiscope.ingest.github.pat import PatClient
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.prompts import latest_prompt
from altiscope.schemas.aggregate import Altitude
from altiscope.store.aggregates import PostgresAggregateStore
from altiscope.store.snapshots import load_snapshot, save_snapshot
from altiscope.summarize.fixture import FixtureProvider, fixture_registry
from tests.conftest import REPO_ROOT
from tests.test_aggregate_generation import good_output
from tests.test_snapshot_store import unique_snapshot

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres"),
]


def test_identity_changes_preserve_versions_and_caches(
    database: str, snapshot: PullRequestSnapshot
):
    snapshot, github_id = unique_snapshot(snapshot)
    original_name = snapshot.repository
    registry = fixture_registry()
    pr_prompt = latest_prompt(REPO_ROOT / "prompts", "pr_summary")
    prompt = latest_prompt(REPO_ROOT / "prompts", "aggregate")
    query = AggregateQuery(
        repository=original_name,
        since=datetime(2026, 6, 1, tzinfo=UTC),
        until=datetime(2026, 6, 30, tzinfo=UTC),
        altitude=Altitude.manager,
    )
    client = Mock(spec=PatClient)
    client.raw = {}
    client.list_merged_pull_requests.return_value = [snapshot.number]

    with psycopg.connect(database, autocommit=True) as conn:
        store = PostgresAggregateStore(conn)

        def resolve(source: PullRequestSnapshot, *, local: bool = False, review: bool = False):
            client.repository_metadata = {
                "id": github_id,
                "full_name": source.repository,
                "default_branch": "main",
            }
            client.fetch_pull_request.return_value = source
            return resolve_reports(
                conn,
                query,
                registry=registry,
                prompt=pr_prompt,
                retention="full",
                client=None if local else client,
                provider=FixtureProvider(['{"review":"Added a lock."}'] if review else []),
            )

        def aggregate(inputs: tuple[ReportInput, ...], *, cached: bool = False):
            return aggregate_reports(
                inputs,
                query=query,
                store=store,
                registry=registry,
                prompt=prompt,
                provider=FixtureProvider([] if cached else [good_output().model_dump_json()]),
            )

        initial = resolve(snapshot, review=True)
        first = load_snapshot(conn, original_name, snapshot.number)
        historical = conn.execute("SELECT * FROM pull_requests WHERE id=%s", (first.id,)).fetchone()
        report = aggregate(initial).report
        assert report is not None
        for name in (original_name.upper(), original_name.replace("m1-test/", "transferred/")):
            query = query.model_copy(update={"repository": name})
            moved = snapshot.model_copy(
                update={
                    "repository": name,
                    "html_url": f"https://github.com/{name}/pull/{snapshot.number}",
                }
            )
            assert resolve(moved) == initial
            assert resolve(moved, local=True) == initial
            assert load_snapshot(conn, name.swapcase(), snapshot.number) == first
            assert aggregate(initial, cached=True).report == report
            assert conn.execute(
                "SELECT owner || '/' || name FROM repositories WHERE github_id=%s", (github_id,)
            ).fetchone() == (name,)
        assert (
            conn.execute("SELECT * FROM pull_requests WHERE id=%s", (first.id,)).fetchone()
            == historical
        )

        # A genuinely edited source creates version 2 and invalidates both report caches.
        edited = moved.model_copy(update={"body": "Changed source text"})
        updated = resolve(edited, review=True)
        assert load_snapshot(conn, edited.repository, snapshot.number).version == 2
        assert updated[0].report_version_id != initial[0].report_version_id
        assert aggregate(updated).report != report
        assert store.get(report.id) == report

        # An occupied locator cannot silently acquire a different GitHub identity.
        with pytest.raises(ValueError, match="different stored GitHub ID"):
            save_snapshot(conn, edited, repository_id=github_id + 1, default_branch="main", raw={})
        assert resolve(edited, local=True) == updated

        # Once the original ID moved away, reuse of its old name creates separate history.
        replacement = snapshot.model_copy(update={"github_id": snapshot.github_id + 1})
        other = save_snapshot(
            conn, replacement, repository_id=github_id + 1, default_branch="main", raw={}
        )
        assert other.version == 1 and other.id != first.id
        query = query.model_copy(update={"repository": original_name})
        github_id += 1
        replacement_inputs = resolve(replacement, review=True)
        assert replacement_inputs != initial
        assert aggregate(replacement_inputs).report != report


def test_empty_remote_window_still_reconciles_rename(database: str, snapshot: PullRequestSnapshot):
    snapshot, github_id = unique_snapshot(snapshot)
    with psycopg.connect(database) as conn:
        first = save_snapshot(
            conn, snapshot, repository_id=github_id, default_branch="main", raw={}
        )
        renamed = snapshot.repository.replace("m1-test/", "renamed/")
        client = Mock(spec=PatClient)
        client.repository_metadata = {
            "id": github_id,
            "full_name": renamed,
            "default_branch": "main",
        }
        client.list_merged_pull_requests.return_value = []
        assert (
            resolve_reports(
                conn,
                AggregateQuery(
                    repository=renamed,
                    since=datetime(2027, 1, 1, tzinfo=UTC),
                    until=datetime(2027, 2, 1, tzinfo=UTC),
                    altitude=Altitude.ic,
                ),
                registry=fixture_registry(),
                prompt=latest_prompt(REPO_ROOT / "prompts", "pr_summary"),
                retention="full",
                client=client,
                provider=FixtureProvider([]),
            )
            == ()
        )
        assert load_snapshot(conn, renamed, snapshot.number) == first
