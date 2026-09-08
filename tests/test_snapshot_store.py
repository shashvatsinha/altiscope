from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC
from uuid import uuid4

import psycopg
import pytest

from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.store.snapshots import load_snapshot, save_snapshot

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres"),
]


def unique_snapshot(snapshot: PullRequestSnapshot):
    snapshot.repository = f"m1-test/{uuid4().hex}"
    return snapshot, uuid4().int % 2**60


def test_snapshot_roundtrip_versions_and_rollback(database: str, snapshot: PullRequestSnapshot):
    snapshot, repo_id = unique_snapshot(snapshot)
    snapshot.comments[1].github_id = snapshot.comments[0].github_id
    with psycopg.connect(database) as conn:
        first = save_snapshot(
            conn, snapshot, repository_id=repo_id, default_branch="main", raw={"test": "raw source"}
        )
        same = save_snapshot(conn, snapshot, repository_id=repo_id, default_branch="main", raw={})
        assert first.id == same.id
        assert load_snapshot(conn, snapshot.repository, snapshot.number).snapshot == snapshot
        changed = snapshot.model_copy(deep=True)
        changed.body += "\nAdditional context"
        second = save_snapshot(conn, changed, repository_id=repo_id, default_branch="main", raw={})
        assert second.id != first.id and second.version == 2
        old = conn.execute("SELECT body,raw FROM pull_requests WHERE id=%s", (first.id,)).fetchone()
        assert old == (snapshot.body, {"test": "raw source"})
        broken = changed.model_copy(deep=True)
        broken.body += " should roll back"
        broken.comments.append(broken.comments[0])
        with pytest.raises(psycopg.errors.UniqueViolation):
            save_snapshot(conn, broken, repository_id=repo_id, default_branch="main", raw={})
        assert load_snapshot(conn, snapshot.repository, snapshot.number).id == second.id


def test_concurrent_identical_ingestion_has_one_latest(
    database: str, snapshot: PullRequestSnapshot
):
    snapshot, repo_id = unique_snapshot(snapshot)

    def write(_: int):
        with psycopg.connect(database) as conn:
            return save_snapshot(
                conn, snapshot, repository_id=repo_id, default_branch="main", raw={}
            ).id

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(write, range(4)))
    assert len(set(ids)) == 1
    with psycopg.connect(database) as conn:
        row = conn.execute(
            "SELECT count(*) FROM pull_requests WHERE id=ANY(%s) AND is_latest_snapshot", (ids,)
        ).fetchone()
        assert row == (1,)


def test_load_snapshots_in_window_and_find_missing(database: str, snapshot: PullRequestSnapshot):
    from datetime import datetime

    from altiscope.ingest.snapshot import PrState
    from altiscope.store.snapshots import find_missing_pr_numbers, load_snapshots_in_window

    snapshot, repo_id = unique_snapshot(snapshot)

    pr1 = snapshot.model_copy(deep=True)
    pr1.number = 101
    pr1.merged_at = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    pr1.state = PrState.merged

    pr2 = snapshot.model_copy(deep=True)
    pr2.number = 102
    pr2.merged_at = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    pr2.state = PrState.merged

    pr3 = snapshot.model_copy(deep=True)
    pr3.number = 103
    pr3.merged_at = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    pr3.state = PrState.merged

    with psycopg.connect(database) as conn:
        save_snapshot(conn, pr1, repository_id=repo_id, default_branch="main", raw={})
        save_snapshot(conn, pr2, repository_id=repo_id, default_branch="main", raw={})
        save_snapshot(conn, pr3, repository_id=repo_id, default_branch="main", raw={})

        # Query June 2026 window: should include 101 and 102, but not 103
        since = datetime(2026, 6, 1, tzinfo=UTC)
        until = datetime(2026, 6, 30, tzinfo=UTC)
        in_window = load_snapshots_in_window(conn, snapshot.repository, since, until)
        assert [s.snapshot.number for s in in_window] == [101, 102]

        # Query August 2026 (empty window): returns empty list
        empty = load_snapshots_in_window(
            conn,
            snapshot.repository,
            datetime(2026, 8, 1, tzinfo=UTC),
            datetime(2026, 8, 31, tzinfo=UTC),
        )
        assert empty == []

        # Find missing PR numbers
        missing = find_missing_pr_numbers(conn, snapshot.repository, [101, 102, 103, 104, 105])
        assert missing == [104, 105]
