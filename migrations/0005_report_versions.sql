BEGIN;
-- Current aggregate reports are independent of obsolete claim-based scaffolding.
-- Older PR reports, snapshots, calls, and migrations remain intact.
CREATE TABLE aggregate_reports (
    id uuid PRIMARY KEY,
    input_hash text NOT NULL,
    status text NOT NULL CHECK (status IN ('published', 'failed')),
    report jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX aggregate_reports_cache_idx ON aggregate_reports(input_hash, created_at DESC)
    WHERE status = 'published';
CREATE TABLE aggregate_report_inputs (
    report_id uuid NOT NULL REFERENCES aggregate_reports(id),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    pr_summary_id bigint REFERENCES pr_summaries(id),
    child_report_id uuid REFERENCES aggregate_reports(id),
    PRIMARY KEY (report_id, ordinal),
    UNIQUE (report_id, pr_summary_id),
    UNIQUE (report_id, child_report_id),
    CHECK (num_nonnulls(pr_summary_id, child_report_id) = 1),
    CHECK (report_id <> child_report_id)
);
CREATE INDEX aggregate_report_inputs_pr_idx ON aggregate_report_inputs(pr_summary_id);
CREATE INDEX aggregate_report_inputs_child_idx ON aggregate_report_inputs(child_report_id);
CREATE TABLE aggregate_report_calls (
    report_id uuid NOT NULL REFERENCES aggregate_reports(id),
    call_id bigint NOT NULL UNIQUE REFERENCES llm_calls(id),
    PRIMARY KEY (report_id, call_id)
);
COMMIT;
