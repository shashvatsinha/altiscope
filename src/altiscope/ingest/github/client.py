"""The contract the ingestion pipeline needs from GitHub.

Kept as a Protocol so the pipeline can be tested with recorded snapshots and so that a
GitHub App implementation and a PAT implementation share one interface.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Protocol

from altiscope.ingest.snapshot import PullRequestSnapshot


class GitHubClient(Protocol):
    def list_merged_pull_numbers(
        self, repository: str, *, merged_since: datetime, merged_until: datetime | None = None
    ) -> Iterator[int]:
        """Yield PR numbers merged in the window, oldest first. Must paginate fully."""
        ...

    def fetch_pull_request(self, repository: str, number: int) -> PullRequestSnapshot:
        """Fetch everything the summarizer reads: metadata, files with patches, commits,
        reviews, and both conversation and inline comments. Never truncate silently; if
        GitHub omits a patch, leave `patch=None` so the diff policy records it."""
        ...
