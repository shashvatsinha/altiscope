from __future__ import annotations

import os

import psycopg
import pytest

from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.llm.registry import Registry
from altiscope.prompts import latest_prompt
from altiscope.schemas.pr_summary import PrReviewOutput
from altiscope.store.accounts import load_account, load_account_context
from altiscope.store.snapshots import save_snapshot
from altiscope.summarize.fixture import FixtureProvider
from altiscope.summarize.publication import PublicationState
from altiscope.summarize.service import prepare, summarize
from tests.conftest import REPO_ROOT
from tests.test_snapshot_store import unique_snapshot

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres"),
]


def test_success_repair_failure_and_rerun(database: str, snapshot: PullRequestSnapshot):
    snapshot, repo_id = unique_snapshot(snapshot)
    good = PrReviewOutput(review="run() acquires a module-level lock.").model_dump_json()
    bad = '{"review": " "}'
    registry = Registry.load(REPO_ROOT / "config/models.yaml")
    prompt = latest_prompt(REPO_ROOT / "prompts", "pr_summary")
    with psycopg.connect(database) as conn:
        stored = save_snapshot(conn, snapshot, repository_id=repo_id, default_branch="main", raw={})
        first = summarize(
            conn,
            stored,
            registry=registry,
            prompt=prompt,
            retention="full",
            provider=FixtureProvider([bad, bad]),
        )
        assert (
            load_account(conn, stored.id, prepare(snapshot)).state == PublicationState.needs_review
        )
        repaired = summarize(
            conn,
            stored,
            registry=registry,
            prompt=prompt,
            retention="hashes_only",
            provider=FixtureProvider([bad, good]),
        )
        assert repaired != first
        assert load_account(conn, stored.id, prepare(snapshot)).state == PublicationState.published
        second = summarize(
            conn,
            stored,
            registry=registry,
            prompt=prompt,
            retention="full",
            provider=FixtureProvider([good]),
        )
        assert second != repaired
        rows = conn.execute(
            "SELECT is_current FROM pr_summaries WHERE pull_request_id=%s ORDER BY id", (stored.id,)
        ).fetchall()
        assert rows == [(False,), (False,), (True,)]
        row = conn.execute(
            "SELECT request_payload,response_text,response_hash FROM llm_calls "
            "WHERE id=(SELECT llm_call_id FROM pr_summaries WHERE id=%s)",
            (repaired,),
        ).fetchone()
        assert row and row[0] is None and row[1] is None and len(row[2]) == 64
        calls = conn.execute(
            "SELECT pull_request_id,attempt_ordinal,generation_id FROM llm_calls "
            "WHERE pull_request_id=%s ORDER BY id",
            (stored.id,),
        ).fetchall()
        assert len(calls) == 5
        assert [call[1] for call in calls] == [1, 2, 1, 2, 1]
        assert calls[0][2] == calls[1][2] and calls[2][2] == calls[3][2]
        assert calls[0][2] != calls[2][2]
        source = conn.execute(
            "SELECT source_text FROM prompt_versions WHERE content_hash=%s",
            (prompt.content_hash,),
        ).fetchone()
        assert source == (prompt.source_text,)

        failed = summarize(
            conn,
            stored,
            registry=registry,
            prompt=prompt,
            retention="full",
            provider=FixtureProvider([bad, bad]),
        )
        assert failed != second
        published = load_account(conn, stored.id, prepare(snapshot))
        assert published.state == PublicationState.published
        assert published.output and published.output.review == "run() acquires a module-level lock."
        assert conn.execute(
            "SELECT narrative,schema_version,pull_request_id FROM pr_summaries WHERE id=%s",
            (second,),
        ).fetchone() == (published.output.review, 3, stored.id)
        assert conn.execute("SELECT to_regclass('public.pr_claims') IS NOT NULL").fetchone() == (
            False,
        )

        saved_context = prepare(snapshot)
        restored = load_account_context(conn, stored.id, snapshot)
        assert restored.facts == saved_context.facts
        assert restored.manifest == saved_context.manifest
        assert restored.snapshot == snapshot
