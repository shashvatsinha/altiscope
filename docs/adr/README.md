# Architecture decision records

An Architecture Decision Record (ADR) explains one design choice, the alternatives
considered, and its consequences. These records describe proposals; they do not imply
that the full design is implemented. See the [architecture](../ARCHITECTURE.md) for
implementation status.

Status stays `proposed` until owner review, then becomes `accepted` or `superseded`.
Keep the reasoning concise. Add a superseding record when reversing a decision.

| # | Decision | Status |
|---|---|---|
| [0001](0001-python-backend.md) | Python for the backend | proposed |
| [0002](0002-postgres-only.md) | Postgres as the only supported database | proposed |
| [0003](0003-merged-pr-atomic-unit.md) | Summarize one merged pull request at a time | proposed |
| [0004](0004-provenance-as-rows.md) | Store evidence links in relational tables | proposed |
| [0005](0005-model-registry-routing.md) | Configure model selection in a registry | proposed |
| [0006](0006-github-app-ingestion.md) | Use a GitHub App for organization access | proposed |
| [0007](0007-accuracy-over-breadth.md) | Check accuracy and expose omissions | proposed |
| [0008](0008-query-time-aggregation.md) | Build reports on demand through a summary tree | proposed |
| [0009](0009-m1-publication-contract.md) | M1 claims-only publication with unverified interpretation | superseded by 0010 |
| [0010](0010-pr-review-provenance.md) | PR-level reviews and provenance; supersedes 0009 | accepted |
| [0011](0011-aggregate-report-provenance.md) | Aggregate report references and original-PR coverage | accepted |
