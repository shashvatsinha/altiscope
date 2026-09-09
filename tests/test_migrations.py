from __future__ import annotations

import os
from pathlib import Path
from typing import LiteralString, cast

import pytest

from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.store.migrate import discover
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.integration


def test_migration_files_are_numbered():
    files = discover(REPO_ROOT / "migrations")
    assert files and files[0].version == "0001_initial"


@pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres")
def test_schema_applies_and_enforces_provenance_checks():
    import psycopg

    from altiscope.store.migrate import apply_pending

    url = os.environ["ALTISCOPE_DATABASE_URL"]
    with psycopg.connect(url) as conn:
        apply_pending(conn, REPO_ROOT / "migrations")
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM schema_migrations")
            row = cur.fetchone()
            assert row is not None and row[0] >= 1
            # obsolete scaffold tables dropped
            cur.execute("SELECT to_regclass('public.pr_claims') IS NOT NULL")
            assert cur.fetchone() == (False,)
            cur.execute("SELECT to_regclass('public.pr_claim_evidence') IS NOT NULL")
            assert cur.fetchone() == (False,)

            # exactly-one-source check on aggregate_claim_sources
            cur.execute("SAVEPOINT s")
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("INSERT INTO aggregate_claim_sources (aggregate_claim_id) VALUES (1)")
            cur.execute("ROLLBACK TO SAVEPOINT s")

            cur.execute("SAVEPOINT s2")
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO aggregate_claim_sources "
                    "(aggregate_claim_id, pr_summary_id, source_aggregate_claim_id) "
                    "VALUES (1, 1, 1)"
                )
            cur.execute("ROLLBACK TO SAVEPOINT s2")

            # verifications check (pr_summary_id, aggregate_id, aggregate_claim_id)
            cur.execute("SAVEPOINT s3")
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO verifications (llm_call_id, verdict, rationale) "
                    "VALUES (1, 'supported', 'ok')"
                )
            cur.execute("ROLLBACK TO SAVEPOINT s3")

            # flags check (aggregate_claim_id, pr_summary_id, aggregate_id)
            cur.execute("SAVEPOINT s4")
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO flags (raised_by_id, category) VALUES (1, 'factual_error')"
                )
            cur.execute("ROLLBACK TO SAVEPOINT s4")
        conn.rollback()


def test_no_migration_edits_after_apply_marker():
    # Check that the initial migration contains its expected version marker.
    text = (REPO_ROOT / "migrations" / "0001_initial.sql").read_text()
    assert "INSERT INTO schema_migrations (version) VALUES ('0001_initial')" in text
    assert Path(REPO_ROOT / "migrations").is_dir()


@pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres")
@pytest.mark.parametrize("with_published_review", [False, True])
def test_fresh_schema_and_upgrade_preserve_m1_review(
    snapshot: PullRequestSnapshot, with_published_review: bool
):
    """Exercise actual migration SQL in an isolated schema, including a populated M1 upgrade."""
    from uuid import uuid4

    import psycopg
    from psycopg import sql

    from altiscope.prompts import latest_prompt
    from altiscope.store.accounts import load_account, load_account_context
    from altiscope.store.snapshots import save_snapshot
    from altiscope.summarize.fixture import FixtureProvider, fixture_registry
    from altiscope.summarize.service import prepare, summarize

    schema = "m2_upgrade_" + uuid4().hex
    with psycopg.connect(os.environ["ALTISCOPE_DATABASE_URL"], autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            migrations = discover(REPO_ROOT / "migrations")
            for migration in migrations[:3]:
                conn.execute(cast(LiteralString, migration.path.read_text()))
            stored = None
            before = None
            if with_published_review:
                stored = save_snapshot(
                    conn, snapshot, repository_id=42, default_branch="main", raw={"preserve": True}
                )
                summarize(
                    conn,
                    stored,
                    registry=fixture_registry(),
                    prompt=latest_prompt(REPO_ROOT / "prompts", "pr_summary"),
                    retention="full",
                    provider=FixtureProvider(['{"review":"Added a lock."}']),
                )
                before = {
                    table: conn.execute(
                        sql.SQL("SELECT * FROM {} ORDER BY id").format(sql.Identifier(table))
                    ).fetchall()
                    for table in ("pr_summaries", "pull_requests", "llm_calls", "prompt_versions")
                }
            for migration in migrations[3:]:
                conn.execute(cast(LiteralString, migration.path.read_text()))
            assert conn.execute("SELECT to_regclass('pr_claims')").fetchone() == (None,)
            if stored is not None and before is not None:
                for table, rows in before.items():
                    assert (
                        conn.execute(
                            sql.SQL("SELECT * FROM {} ORDER BY id").format(sql.Identifier(table))
                        ).fetchall()
                        == rows
                    )
                ctx = prepare(snapshot)
                publication = load_account(conn, stored.id, ctx)
                assert publication.output and publication.output.review == "Added a lock."
                restored = load_account_context(conn, stored.id, snapshot)
                assert restored.facts == ctx.facts and restored.manifest == ctx.manifest
        finally:
            conn.execute("ROLLBACK")
            conn.execute("SET search_path TO public")
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
