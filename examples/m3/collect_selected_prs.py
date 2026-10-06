"""Collect the selected public 20-PR set without displaying held-out source content."""

from __future__ import annotations

import os
import subprocess

from altiscope.config import load_settings
from altiscope.ingest.github.pat import PatClient
from altiscope.store.db import connect
from altiscope.store.snapshots import save_snapshot

DEVELOPMENT = (19, 22, 33, 48, 71, 97, 129, 169, 196, 303, 1153, 1160)
HELD_OUT = (1259, 1256, 1241, 1253, 1249, 1245, 1201, 1260)


def _github_token() -> str:
    configured = os.environ.get("ALTISCOPE_GITHUB_TOKEN")
    if configured:
        return configured
    result = subprocess.run(
        ["gh", "auth", "token", "--hostname", "github.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    token = result.stdout.strip()
    if not token:
        raise ValueError("GitHub CLI has no github.com token")
    return token


def main() -> None:
    settings = load_settings()
    client = PatClient(_github_token(), base_url=settings.github_api_base)
    try:
        with connect(settings.database_url) as conn:
            for group, numbers in (("development", DEVELOPMENT), ("held_out", HELD_OUT)):
                for number in numbers:
                    snapshot = client.fetch_pull_request("microsoft/markitdown", number)
                    metadata = client.repository_metadata
                    if int(metadata["id"]) != 888_092_115:
                        raise ValueError("selected repository numeric ID changed")
                    if snapshot.state != "merged" or snapshot.base_ref != "main":
                        raise ValueError(f"selected PR #{number} is no longer eligible")
                    stored = save_snapshot(
                        conn,
                        snapshot,
                        repository_id=888_092_115,
                        default_branch=str(metadata["default_branch"]),
                        raw=client.raw,
                    )
                    print(f"{group} PR #{number}: snapshot {stored.id} v{stored.version}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
