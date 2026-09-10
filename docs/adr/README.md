# Architecture decision records

These notes explain why a design was chosen. Start with the
[architecture](../ARCHITECTURE.md) for how the application works today.

For the current report design, read **[0011: report inputs and history](0011-aggregate-report-provenance.md)**
and [0010: individual PR reports](0010-pr-review-provenance.md). Together they describe
useful summaries, drill-down to their inputs, and a record of the model and prompt used.
They do not require model-selected citations or coverage percentages.

A **proposed** record is an idea awaiting owner acceptance. **Accepted** means the
direction was approved, not that all code is finished. **Superseded** means a newer
record replaced the decision. Older proposals may be partly superseded; follow the
newer records where they disagree. When reversing a decision, add a new record and
link it from the old one so the reasoning remains available.

| Record | Subject | Status |
|---|---|---|
| [0001](0001-python-backend.md) | Python backend | Proposed |
| [0002](0002-postgres-only.md) | Postgres database | Proposed |
| [0003](0003-merged-pr-atomic-unit.md) | Start with merged PRs | Proposed; version rules updated by 0011 |
| [0004](0004-provenance-as-rows.md) | Store source relationships in tables | Claim links replaced by 0010 and 0011 |
| [0005](0005-model-registry-routing.md) | Configure model selection | Proposed |
| [0006](0006-github-app-ingestion.md) | GitHub App for organization access | Proposed |
| [0007](0007-accuracy-over-breadth.md) | Accuracy and input limitations | Citation, assessment, and coverage rules replaced by 0010 and 0011 |
| [0008](0008-query-time-aggregation.md) | Combine reports on request | Proposed; input and version rules replaced by 0011 |
| [0009](0009-m1-publication-contract.md) | Earlier claim-based PR output | Superseded by 0010 |
| [0010](0010-pr-review-provenance.md) | Overall PR reports and generation history | Accepted |
| [0011](0011-aggregate-report-provenance.md) | Record all report inputs and preserve versions | Accepted |
