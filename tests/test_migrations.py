from __future__ import annotations

import os
from pathlib import Path

import pytest
from tests.conftest import REPO_ROOT

from altiscope.store.migrate import discover

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
            # exactly-one-source check on aggregate_claim_sources
            cur.execute("SAVEPOINT s")
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("INSERT INTO aggregate_claim_sources (aggregate_claim_id) VALUES (1)")
            cur.execute("ROLLBACK TO SAVEPOINT s")
        conn.rollback()


def test_no_migration_edits_after_apply_marker():
    # Guard against editing 0001 in place: its version string is asserted here so a
    # rename is a conscious act.
    text = (REPO_ROOT / "migrations" / "0001_initial.sql").read_text()
    assert "INSERT INTO schema_migrations (version) VALUES ('0001_initial')" in text
    assert Path(REPO_ROOT / "migrations").is_dir()
