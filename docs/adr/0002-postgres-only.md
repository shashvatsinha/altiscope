# ADR-0002: Postgres as the only supported database

Status: proposed

## Context

An open-source tool benefits from a zero-dependency quickstart, which argues for SQLite.
The provenance model relies on foreign keys, check constraints, JSONB for facts and
manifests, and `SKIP LOCKED` for background jobs. The deployment target for every
organization above hobby scale is Postgres.

## Decision

Postgres 15+ only. Local development uses `docker compose up db`. Migrations are plain
SQL files applied in order by a small runner; the schema is meant to be read.

## Rejected

- **SQLite + Postgres.** Two dialects means either a lowest-common-denominator schema
  (losing JSONB operators and `SKIP LOCKED`) or a test matrix that doubles. Every
  provenance query would need to be verified twice.
- **An ORM with migrations generated from models.** SQLAlchemy would be a reasonable
  choice; the reason to avoid it now is that the schema *is* the design artifact for
  provenance, and hand-written SQL keeps it legible and reviewable. This can be revisited
  if the query layer becomes repetitive.

## Consequences

- Quickstart requires Docker or a local Postgres. The README says so up front.
- All integration tests run against a real Postgres in CI.
