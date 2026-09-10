"""Synthetic billing repository replay through the real aggregate execution engine."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from altiscope.aggregate.inputs import ReportInput, render_inputs
from altiscope.aggregate.planner import estimate_aggregate_request_tokens
from altiscope.aggregate.render import render_aggregate
from altiscope.aggregate.service import (
    AggregateQuery,
    AggregateStore,
    MemoryAggregateStore,
    aggregate_reports,
)
from altiscope.config import load_settings
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.prompts import latest_prompt
from altiscope.schemas.aggregate import Altitude
from altiscope.store.aggregates import PostgresAggregateStore, load_pr_input
from altiscope.store.db import connect
from altiscope.store.snapshots import save_snapshot
from altiscope.summarize.fixture import FixtureProvider, fixture_registry
from altiscope.summarize.service import prepare, summarize


def run_demo(altitude: str, *, persist: bool = False, multi_level: bool = False) -> str:
    settings = load_settings()
    root = Path("examples/m2")
    query = AggregateQuery(
        repository="altiscope-demo/billing",
        since=datetime(2026, 6, 1, tzinfo=UTC),
        until=datetime(2026, 6, 30, 23, 59, 59, 999999, tzinfo=UTC),
        altitude=Altitude.from_str(altitude),
    )
    entries = json.loads((root / "repository.json").read_text())
    registry = fixture_registry()
    prompt = latest_prompt(settings.prompts_dir, "aggregate")
    inputs: list[ReportInput] = []
    conn = connect(settings.database_url) if persist else None
    try:
        if conn is not None:
            conn.autocommit = True
            store: AggregateStore = PostgresAggregateStore(conn)
            for entry in entries:
                snapshot = PullRequestSnapshot.model_validate(entry["snapshot"])
                stored = save_snapshot(
                    conn,
                    snapshot,
                    repository_id=9100000000000000,
                    default_branch="main",
                    raw={"fixture": True},
                )
                row = conn.execute(
                    "SELECT id FROM pr_summaries WHERE pull_request_id=%s AND status='published' "
                    "ORDER BY id DESC LIMIT 1",
                    (stored.id,),
                ).fetchone()
                report_id = (
                    int(row[0])
                    if row
                    else summarize(
                        conn,
                        stored,
                        registry=registry,
                        prompt=latest_prompt(settings.prompts_dir, "pr_summary"),
                        retention=settings.llm_payload_retention,
                        provider=FixtureProvider([json.dumps({"review": entry["review"]})]),
                    )
                )
                inputs.append(load_pr_input(conn, report_id))
        else:
            store = MemoryAggregateStore()
            for entry in entries:
                snapshot = PullRequestSnapshot.model_validate(entry["snapshot"])
                inputs.append(
                    ReportInput(
                        "pr",
                        f"demo-{snapshot.number}",
                        json.dumps(
                            dict(
                                number=snapshot.number,
                                title=snapshot.title,
                                review=entry["review"],
                                facts=prepare(snapshot).facts.model_dump(mode="json"),
                                input_manifest=prepare(snapshot).manifest.model_dump(mode="json"),
                            ),
                            sort_keys=True,
                        ),
                        (snapshot.html_url,),
                    )
                )
        if multi_level:
            # Deliberately small demo capacity: two original reports fit, four do not.
            registry.input_budget_fraction = 1
            registry.stages["aggregate"].reserved_output_tokens = 256
            size = max(
                estimate_aggregate_request_tokens(
                    prompt.body, render_inputs(query.instruction(), tuple(inputs[i : i + 2]))
                )
                for i in (0, 2)
            )
            # Child reports need enough room to be combined, even with very short PR fixtures.
            registry.models["fixture"].context_window = size + 256 + 32
        responses = (
            [json.dumps(child) for child in json.loads((root / "children.json").read_text())]
            if multi_level
            else []
        )
        responses.append((root / f"{query.altitude.value}.json").read_text())
        first = aggregate_reports(
            tuple(inputs),
            query=query,
            store=store,
            registry=registry,
            prompt=prompt,
            provider=FixtureProvider(responses),
            force=True,
        )
        assert first.report is not None
        second = aggregate_reports(
            tuple(inputs),
            query=query,
            store=store,
            registry=registry,
            prompt=prompt,
            provider=FixtureProvider([]),
        )
        assert second.calls == 0 and second.report == first.report
        output = "SYNTHETIC FIXTURE DEMO — recorded responses, no live model calls.\n"
        output += "PR URLs illustrate navigation; this is not a real GitHub repository.\n"
        output += render_aggregate(first.report, navigation=persist)
        output += f"\nAggregate model calls: {first.calls}; repeat request: {second.calls}.\n"
        if persist:
            output += f"Inspect: altiscope show-aggregate {first.report.id} --verbose\n"
        return output
    finally:
        if conn is not None:
            conn.close()
