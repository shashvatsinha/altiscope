"""Append-only aggregate versions, exact input edges, and shared model-call history."""

from __future__ import annotations

import json
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from altiscope.aggregate.generate import GeneratedAggregate
from altiscope.aggregate.inputs import ReportInput
from altiscope.aggregate.service import SavedAggregate
from altiscope.llm.registry import Registry
from altiscope.llm.router import RoutingDecision
from altiscope.prompts import Prompt
from altiscope.schemas.aggregate import AggregateOutput
from altiscope.store.calls import save_calls


def load_pr_input(conn: psycopg.Connection, report_id: int) -> ReportInput:
    row = conn.execute(
        "SELECT s.narrative,p.html_url,p.source_hash,s.facts,s.input_manifest,p.title,p.number "
        "FROM pr_summaries s JOIN pull_requests p ON p.id=s.pull_request_id "
        "WHERE s.id=%s AND s.status='published'",
        (report_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Published PR report {report_id} not found")
    # Saved metadata supplies context and limitations even when the review is terse.

    text = json.dumps(
        dict(number=row[6], title=row[5], review=row[0], facts=row[3], input_manifest=row[4]),
        sort_keys=True,
    )
    return ReportInput("pr", str(report_id), text, (str(row[1]),), str(row[2]))


class PostgresAggregateStore:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def find(self, input_hash: str) -> SavedAggregate | None:
        with self.conn.transaction():
            row = self.conn.execute(
                "SELECT report FROM aggregate_reports WHERE input_hash=%s AND status='published' "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (input_hash,),
            ).fetchone()
        return SavedAggregate.model_validate(row[0]) if row else None

    def get(self, report_id: str) -> SavedAggregate:
        identifier = UUID(report_id)
        with self.conn.transaction():
            row = self.conn.execute(
                "SELECT report FROM aggregate_reports WHERE id=%s", (identifier,)
            ).fetchone()
        if row is None:
            raise ValueError("Aggregate report not found")
        return SavedAggregate.model_validate(row[0])

    def save(
        self,
        report: SavedAggregate,
        generated: GeneratedAggregate,
        *,
        prompt: Prompt,
        decision: RoutingDecision,
        registry: Registry,
        retention: str,
    ) -> None:
        if report.inputs != generated.inputs or report.output != generated.output:
            raise ValueError("Report does not match generated output and inputs")
        with self.conn.transaction():
            # Re-load exact immutable records, never their current replacements.
            for supplied in report.inputs:
                expected = (
                    load_pr_input(self.conn, int(supplied.report_version_id))
                    if supplied.kind == "pr"
                    else self.get(supplied.report_version_id).as_input()
                )
                if expected != supplied:
                    raise ValueError("Aggregate input does not match stored report version")
            self.conn.execute(
                "INSERT INTO aggregate_reports(id,input_hash,status,report,created_at) "
                "VALUES(%s,%s,%s,%s,%s)",
                (
                    UUID(report.id),
                    report.input_hash,
                    "published" if report.output else "failed",
                    Jsonb(report.model_dump(mode="json")),
                    report.created_at,
                ),
            )
            for ordinal, supplied in enumerate(report.inputs, 1):
                self.conn.execute(
                    "INSERT INTO aggregate_report_inputs"
                    "(report_id,ordinal,pr_summary_id,child_report_id) VALUES(%s,%s,%s,%s)",
                    (
                        UUID(report.id),
                        ordinal,
                        int(supplied.report_version_id) if supplied.kind == "pr" else None,
                        UUID(supplied.report_version_id) if supplied.kind == "aggregate" else None,
                    ),
                )
            _, call_ids = save_calls(
                self.conn,
                attempts=generated.attempts,
                output_type=AggregateOutput,
                prompt=prompt,
                decision=decision,
                registry=registry,
                retention=retention,
            )
            for call_id in call_ids:
                self.conn.execute(
                    "INSERT INTO aggregate_report_calls(report_id,call_id) VALUES(%s,%s)",
                    (UUID(report.id), call_id),
                )
