# Architecture decision records

One file per decision. Status is `proposed` until the repository owner has reviewed it,
then `accepted` or `superseded`. Keep them short; the point is the reasoning, and the
alternatives that were considered and rejected, so a future contributor does not re-open
a settled question without new information.

| # | Decision | Status |
|---|---|---|
| [0001](0001-python-backend.md) | Python for the backend | proposed |
| [0002](0002-postgres-only.md) | Postgres as the only supported database | proposed |
| [0003](0003-merged-pr-atomic-unit.md) | The merged pull request is the atomic unit | proposed |
| [0004](0004-provenance-as-rows.md) | Provenance is rows and foreign keys, never prose | proposed |
| [0005](0005-model-registry-routing.md) | Model choice is a routing decision from a config registry | proposed |
| [0006](0006-github-app-ingestion.md) | GitHub App as the primary ingestion identity | proposed |
| [0007](0007-accuracy-over-breadth.md) | Accuracy mechanisms: verification, coverage, flags, no people-judgments | proposed |
| [0008](0008-query-time-aggregation.md) | Aggregation is on demand with a query-time reduction tree | proposed |
