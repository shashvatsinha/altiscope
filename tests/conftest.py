from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from altiscope.ingest.snapshot import (
    CommentKind,
    FileStatus,
    PrComment,
    PrCommit,
    PrFile,
    PrReview,
    PrState,
    PullRequestSnapshot,
    ReviewState,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

PATCH_MAIN = """@@ -1,4 +1,6 @@
 import os
+import threading
+_lock = threading.Lock()
 def run():
-    return os.getcwd()
+    with _lock:
+        return os.getcwd()
"""

PATCH_TEST = """@@ -0,0 +1,3 @@
+def test_run():
+    from app.main import run
+    assert run()
"""


@pytest.fixture
def snapshot() -> PullRequestSnapshot:
    created = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    return PullRequestSnapshot(
        repository="acme/widgets",
        number=42,
        github_id=1042,
        title="Make run() thread-safe",
        body="Wraps run() in a lock so concurrent callers don't race.\n\nFixes #17. Adds a test.",
        author_login="alice",
        state=PrState.merged,
        base_ref="main",
        head_ref="alice/lock",
        merge_commit_sha="abcdef1234567",
        created_at=created,
        updated_at=created + timedelta(hours=5),
        closed_at=created + timedelta(hours=5),
        merged_at=created + timedelta(hours=5),
        merged_by_login="bob",
        additions=6,
        deletions=1,
        changed_files=3,
        labels=["bug"],
        html_url="https://github.com/acme/widgets/pull/42",
        files=[
            PrFile(
                path="app/main.py",
                status=FileStatus.modified,
                additions=3,
                deletions=1,
                patch=PATCH_MAIN,
            ),
            PrFile(
                path="tests/test_main.py",
                status=FileStatus.added,
                additions=3,
                deletions=0,
                patch=PATCH_TEST,
            ),
            PrFile(
                path="package-lock.json",
                status=FileStatus.modified,
                additions=400,
                deletions=380,
                patch="@@ -1 +1 @@\n-x\n+y\n",
            ),
        ],
        commits=[PrCommit(sha="1111111aaaaaaa", message="add lock", author_login="alice")],
        reviews=[
            PrReview(
                github_id=1,
                author_login="bob",
                state=ReviewState.changes_requested,
                body="needs a test",
            ),
            PrReview(github_id=2, author_login="bob", state=ReviewState.approved),
        ],
        comments=[
            PrComment(
                github_id=501,
                kind=CommentKind.review,
                author_login="bob",
                body="Should this lock be re-entrant?",
                created_at=created + timedelta(hours=1),
                path="app/main.py",
                line=3,
            ),
            PrComment(
                github_id=502,
                kind=CommentKind.issue,
                author_login="alice",
                body="Added the test you asked for.",
                created_at=created + timedelta(hours=2),
            ),
        ],
    )


@pytest.fixture
def database():
    import os

    import psycopg

    from altiscope.store.migrate import apply_pending

    url = os.environ["ALTISCOPE_DATABASE_URL"]
    with psycopg.connect(url) as conn:
        apply_pending(conn, REPO_ROOT / "migrations")
    return url
