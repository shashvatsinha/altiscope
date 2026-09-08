"""Transactional immutable source versions and relational evidence records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from altiscope.ingest.diff_policy import apply
from altiscope.ingest.snapshot import PullRequestSnapshot


def insert(conn: psycopg.Connection, table: str, values: dict[str, Any]) -> int:
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING id").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, values)),
        sql.SQL(", ").join(sql.Placeholder() for _ in values),
    )
    row = conn.execute(query, list(values.values())).fetchone()
    assert row is not None
    return int(row[0])


def person(conn: psycopg.Connection, login: str | None) -> int | None:
    if login is None:
        return None
    row = conn.execute(
        "INSERT INTO people (github_login) VALUES (%s) "
        "ON CONFLICT (github_login) DO UPDATE SET github_login=EXCLUDED.github_login RETURNING id",
        (login,),
    ).fetchone()
    assert row is not None
    return int(row[0])


@dataclass(frozen=True)
class StoredSnapshot:
    id: int
    version: int
    snapshot: PullRequestSnapshot


def save_snapshot(
    conn: psycopg.Connection,
    snapshot: PullRequestSnapshot,
    *,
    repository_id: int,
    default_branch: str,
    raw: dict[str, Any],
) -> StoredSnapshot:
    """Lock the repository while selecting and advancing this PR's latest version."""
    if len(snapshot.files) != snapshot.changed_files:
        raise ValueError("Incomplete file collection; snapshot not saved")
    normalized = snapshot.model_dump(mode="json")
    source_hash = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    owner, name = snapshot.repository.split("/")
    with conn.transaction():
        # Serialize before INSERT too: concurrent conflicts across both repository
        # unique indexes can otherwise race before ON CONFLICT selects its target.
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (snapshot.repository.lower(),)
        )
        row = conn.execute(
            "INSERT INTO repositories (github_id, owner, name, default_branch, visibility) "
            "VALUES (%s,%s,%s,%s,'public') ON CONFLICT (github_id) DO UPDATE "
            "SET default_branch=EXCLUDED.default_branch RETURNING id",
            (repository_id, owner, name, default_branch),
        ).fetchone()
        assert row is not None
        repo_id = int(row[0])
        previous = conn.execute(
            "SELECT id, snapshot_version, source_hash FROM pull_requests "
            "WHERE repository_id=%s AND number=%s AND is_latest_snapshot FOR UPDATE",
            (repo_id, snapshot.number),
        ).fetchone()
        if previous and previous[2] == source_hash:
            return StoredSnapshot(int(previous[0]), int(previous[1]), snapshot)
        version = int(previous[1]) + 1 if previous else 1
        conn.execute(
            "UPDATE pull_requests SET is_latest_snapshot=false "
            "WHERE repository_id=%s AND number=%s AND is_latest_snapshot",
            (repo_id, snapshot.number),
        )
        fields = snapshot.model_dump(
            exclude={
                "repository",
                "author_login",
                "merged_by_login",
                "files",
                "commits",
                "reviews",
                "comments",
            }
        )
        fields.update(
            repository_id=repo_id,
            snapshot_version=version,
            author_id=person(conn, snapshot.author_login),
            merged_by_id=person(conn, snapshot.merged_by_login),
            raw=Jsonb(raw),
            normalized_snapshot=Jsonb(normalized),
            source_hash=source_hash,
        )
        snapshot_id = insert(conn, "pull_requests", fields)
        decisions = {d.path: d for d in apply(snapshot.files).decisions}
        for file in snapshot.files:
            decision = decisions[file.path]
            insert(
                conn,
                "pr_files",
                dict(
                    file.model_dump(),
                    pull_request_id=snapshot_id,
                    included=decision.included,
                    exclusion_reason=decision.reason,
                ),
            )
        for commit in snapshot.commits:
            values = commit.model_dump(exclude={"author_login"})
            insert(
                conn,
                "pr_commits",
                dict(
                    values, pull_request_id=snapshot_id, author_id=person(conn, commit.author_login)
                ),
            )
        for review in snapshot.reviews:
            values = review.model_dump(exclude={"author_login"})
            insert(
                conn,
                "pr_reviews",
                dict(
                    values, pull_request_id=snapshot_id, author_id=person(conn, review.author_login)
                ),
            )
        for comment in snapshot.comments:
            values = comment.model_dump(exclude={"author_login"})
            insert(
                conn,
                "pr_comments",
                dict(
                    values,
                    pull_request_id=snapshot_id,
                    author_id=person(conn, comment.author_login),
                ),
            )
    return StoredSnapshot(snapshot_id, version, snapshot)


def load_snapshot(conn: psycopg.Connection, repository: str, number: int) -> StoredSnapshot:
    owner, name = repository.split("/")
    row = conn.execute(
        "SELECT p.id, p.snapshot_version, p.normalized_snapshot FROM pull_requests p "
        "JOIN repositories r ON r.id=p.repository_id "
        "WHERE r.owner=%s AND r.name=%s AND p.number=%s AND p.is_latest_snapshot",
        (owner, name, number),
    ).fetchone()
    if row is None:
        raise ValueError("PR has not been ingested")
    return StoredSnapshot(int(row[0]), int(row[1]), PullRequestSnapshot.model_validate(row[2]))
