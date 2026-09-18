"""Freeze prepared sources for the selected 20-PR workflow run.

Print identities, hashes, and estimated sizes only. Source content stays in Postgres.
"""

from __future__ import annotations

import json

from collect_selected_prs import DEVELOPMENT, HELD_OUT

from altiscope.config import load_settings
from altiscope.llm.tokens import estimate_tokens
from altiscope.store.comparisons import freeze_pr_source
from altiscope.store.db import connect
from altiscope.store.snapshots import load_snapshot
from altiscope.summarize.context import render_user_prompt
from altiscope.summarize.service import prepare


def main() -> None:
    settings = load_settings()
    rows: list[dict[str, object]] = []
    with connect(settings.database_url) as conn:
        for group, numbers in (("development", DEVELOPMENT), ("held_out", HELD_OUT)):
            for ordinal, number in enumerate(numbers, 1):
                case_prefix = "dev" if group == "development" else "holdout"
                stored = load_snapshot(conn, "microsoft/markitdown", number)
                repository = conn.execute(
                    "SELECT r.github_id FROM repositories r JOIN pull_requests p "
                    "ON p.repository_id=r.id WHERE p.id=%s",
                    (stored.id,),
                ).fetchone()
                if repository is None or int(repository[0]) != 888_092_115:
                    raise ValueError(f"PR #{number} has an unexpected repository ID")
                context = prepare(stored.snapshot)
                prepared = render_user_prompt(context)
                source = freeze_pr_source(
                    conn,
                    snapshot_id=stored.id,
                    preparation_document={
                        "facts": context.facts.model_dump(mode="json"),
                        "manifest": context.manifest.model_dump(mode="json"),
                    },
                    prepared_text=prepared,
                    preparation_contract={
                        "renderer": "pr-context-v1",
                        "facts": "v1",
                        "policy": "v1",
                    },
                )
                rows.append(
                    {
                        "case_id": f"m3-{case_prefix}-pr-{ordinal:03d}",
                        "group": group,
                        "pr_number": number,
                        "snapshot_id": stored.id,
                        "snapshot_version": stored.version,
                        "source_id": str(source.id),
                        "source_hash": source.content_hash,
                        "prepared_text_hash": source.prepared_text_hash,
                        "estimated_prepared_tokens": estimate_tokens(prepared),
                    }
                )
    print(json.dumps({"kind": "m3-workflow-source-inventory-v1", "cases": rows}, indent=2))


if __name__ == "__main__":
    main()
