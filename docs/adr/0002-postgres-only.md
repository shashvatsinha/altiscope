# ADR-0002: Postgres as the only supported database

Status: proposed

## Context

SQLite would simplify local setup. The proposed storage design uses Postgres JSONB for
facts and input manifests, foreign keys for evidence links, and `SKIP LOCKED` for jobs.
Supporting one database limits the queries and migrations that need testing.

## Decision

Support Postgres 15+. Use `docker compose up db` for local development. Apply numbered
SQL migrations in order with the migration runner.

## Alternatives considered

- **SQLite and Postgres.** Would require database-specific queries or avoiding Postgres
  features such as JSONB operators and `SKIP LOCKED`. Both paths would need testing.
- **An ORM with generated migrations.** Could reduce repetitive query code. For now,
  handwritten SQL keeps the tables and constraints visible during design review.
  Revisit this if the query layer becomes repetitive.

## Consequences

- Setup requires Docker or a local Postgres installation; see
  [Contributing](../../CONTRIBUTING.md).
- CI runs integration tests against Postgres.
