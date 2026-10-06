"""Freeze the selected manager source from eight exact saved PR reports."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from altiscope.aggregate.inputs import render_inputs
from altiscope.config import load_settings
from altiscope.store.aggregates import load_pr_input
from altiscope.store.comparisons import freeze_aggregate_source
from altiscope.store.db import connect

HELD_OUT_ORDER = (1259, 1256, 1241, 1253, 1249, 1245, 1201, 1260)


def main() -> None:
    if len(sys.argv) != len(HELD_OUT_ORDER) + 1:
        raise SystemExit("usage: freeze_openrouter_aggregate.py EIGHT_REPORT_IDS_IN_DATASET_ORDER")
    report_ids = tuple(int(value) for value in sys.argv[1:])
    inventory_path = Path("docs/evaluation/m3-workflow-sources-v1.json")
    inventory = json.loads(inventory_path.read_text())
    snapshot_ids = {
        int(item["pr_number"]): int(item["snapshot_id"])
        for item in inventory["cases"]
        if item["group"] == "held_out"
    }
    if set(snapshot_ids) != set(HELD_OUT_ORDER):
        raise ValueError("frozen source inventory does not match held-out input order")
    with connect(load_settings().database_url) as conn:
        for report_id, expected_number in zip(report_ids, HELD_OUT_ORDER, strict=True):
            row = conn.execute(
                "SELECT p.number,r.github_id,p.id FROM pr_summaries s "
                "JOIN pull_requests p ON p.id=s.pull_request_id "
                "JOIN repositories r ON r.id=p.repository_id "
                "WHERE s.id=%s AND s.status='published'",
                (report_id,),
            ).fetchone()
            if row is None or tuple(int(value) for value in row) != (
                expected_number,
                888_092_115,
                snapshot_ids[expected_number],
            ):
                raise ValueError(
                    f"report {report_id} does not match frozen PR #{expected_number} snapshot"
                )
        inputs = tuple(load_pr_input(conn, report_id) for report_id in report_ids)
        repository = conn.execute(
            "SELECT id FROM repositories WHERE github_id=888092115"
        ).fetchone()
        assert repository is not None
        instruction = (
            "Repository: microsoft/markitdown\n"
            "Merged from 2025-05-21T00:00:00+00:00 through "
            "2025-05-21T23:59:59.999999+00:00 (inclusive).\n"
            "Reader altitude: manager"
        )
        source = freeze_aggregate_source(
            conn,
            repository_id=int(repository[0]),
            inputs=inputs,
            query={
                "repository_id": 888_092_115,
                "since": "2025-05-21T00:00:00Z",
                "until": "2025-05-21T23:59:59.999999Z",
                "selection": "all merged PRs in inclusive UTC window, merged_at then PR number",
                "altitude": "manager",
                "instruction": instruction,
            },
            altitude="manager",
            prepared_text=render_inputs(instruction, inputs),
            preparation_contract={"renderer": "aggregate-inputs-v1"},
        )
    print(f"Aggregate source: {source.id}")
    print(f"Content hash: {source.content_hash}")
    print(f"Prepared text hash: {source.prepared_text_hash}")
    print(f"Exact input report versions: {', '.join(str(value) for value in report_ids)}")


if __name__ == "__main__":
    main()
