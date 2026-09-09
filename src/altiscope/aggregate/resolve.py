"""Refresh window membership, then select or generate current PR reports."""

from __future__ import annotations

import psycopg

from altiscope.aggregate.inputs import ReportInput
from altiscope.aggregate.service import AggregateQuery
from altiscope.ingest.github.pat import PatClient
from altiscope.ingest.snapshot import PrState
from altiscope.llm.provider import Provider
from altiscope.llm.registry import Registry
from altiscope.prompts import Prompt
from altiscope.store.aggregates import load_pr_input
from altiscope.store.snapshots import StoredSnapshot, load_snapshots_in_window, save_snapshot
from altiscope.summarize.service import summarize


def resolve_reports(
    conn: psycopg.Connection,
    query: AggregateQuery,
    *,
    registry: Registry,
    prompt: Prompt,
    retention: str,
    client: PatClient | None,
    provider: Provider | None = None,
) -> tuple[ReportInput, ...]:
    snapshots: list[StoredSnapshot]
    if client is None:
        snapshots = load_snapshots_in_window(conn, query.repository, query.since, query.until)
    else:
        numbers = client.list_merged_pull_requests(query.repository, query.since, query.until)
        snapshots = []
        for number in numbers:
            snapshot = client.fetch_pull_request(query.repository, number)
            if (
                snapshot.state != PrState.merged
                or snapshot.merged_at is None
                or not query.since <= snapshot.merged_at <= query.until
            ):
                raise ValueError("PR window changed during collection; retry the request")
            snapshots.append(
                save_snapshot(
                    conn,
                    snapshot,
                    repository_id=int(client.repository_metadata["id"]),
                    default_branch=client.repository_metadata["default_branch"],
                    raw=client.raw,
                )
            )
        snapshots.sort(
            key=lambda stored: (stored.snapshot.merged_at or query.since, stored.snapshot.number)
        )
    reports: list[ReportInput] = []
    for stored in snapshots:
        row = conn.execute(
            "SELECT id FROM pr_summaries WHERE pull_request_id=%s AND status='published' "
            "ORDER BY is_current DESC,id DESC LIMIT 1",
            (stored.id,),
        ).fetchone()
        report_id = (
            int(row[0])
            if row
            else summarize(
                conn,
                stored,
                registry=registry,
                prompt=prompt,
                retention=retention,
                provider=provider,
            )
        )
        # A failed PR generation stops the aggregate instead of silently excluding an input.
        reports.append(load_pr_input(conn, report_id))
    return tuple(reports)
