# Roadmap

Ordered. Each item should land with tests and, where it touches a decision, an ADR.

## 0. Owner review of the proposal

Answer the open questions in `docs/ARCHITECTURE.md` §10 and mark ADRs accepted or
amended. Nothing below should be built at scale before this.

## 1. Vertical slice on one repository (no UI)

- `store/`: connection pool, migration runner (done), typed query helpers.
- `ingest/github`: REST+GraphQL client with PAT auth, rate-limit backoff, PR list by
  merged range, PR detail (files with patches, reviews, comments, commits), and a
  write path into snapshot tables applying `diff_policy`.
- `summarize/`: facts computation from snapshot (done as pure function), prompt
  assembly, Anthropic call via structured output, evidence validation (done), one repair
  retry, storage with `llm_calls` provenance.
- `verify/`: second-model verification per claim, verdict storage.
- CLI: `altiscope ingest owner/repo --since 2026-01-01`, `altiscope summarize --pending`,
  `altiscope show pr owner/repo#123` printing claims with evidence.
- Golden set: 20 real PRs from a public repository with human-reviewed summaries,
  checked into `tests/golden/`, and a test that runs the validators over them.

## 2. Aggregation

- Query resolution (subjects, window, temporal team membership).
- Planner (done as pure function) wired to token counting via the provider.
- Aggregate call with per-call opaque source tokens, validation, coverage (done as pure
  function), storage, cache lookup by input hash.
- CLI: `altiscope aggregate --person alice --from 2026-04-01 --to 2026-07-01 --altitude manager`.

## 3. GitHub App and organization ingestion

- App auth (JWT → installation token), installation discovery, repository enumeration.
- Team sync from GitHub Teams into temporal memberships; manual override import (CSV).
- Postgres job queue and `altiscope worker`.
- Webhook receiver as a freshness optimization.

## 4. API and UI

- FastAPI JSON API: summaries, aggregates, drill-down, flags, coverage.
- Permission check at the boundary mirroring GitHub repository read access.
- Server-rendered UI: PR summary page with claim → evidence highlighting; aggregate page
  with coverage panel and drill-down; flag dialog.
- OIDC and GitHub OAuth login. Audit log.

## 5. Evaluation loop

- Flags → eval set export. Prompt/model regression runner comparing claim-level
  agreement with human corrections. Report per model per stage.
- Model comparison view: same PR, two summaries, verdicts side by side.

## 6. Hardening for organizations

- Bedrock, Vertex and Foundry clients for the Anthropic adapter; a Gemini adapter.
  (The chat-completions adapter already covers OpenAI, Azure and open-source servers.)
- Per-model golden-set results published in the registry so "which models are good
  enough for verification" is answered by data.
- Payload retention modes; encryption at rest guidance; backup/restore docs.
- Helm chart or equivalent; health endpoints; metrics.

## Later, deliberately not now

- Summaries of open or abandoned PRs (needs an invalidation rule; open question 1).
- Direct-to-main commits reported as a per-repository fact.
- Lenses (reliability, security) mapping to claim kinds.
- Quality/security/compliance findings as a new analysis kind reusing the claim +
  evidence shape.
