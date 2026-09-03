# ADR-0004: Provenance is rows and foreign keys, never prose

Status: proposed

## Context

A citation embedded as text ("see #412, #418") cannot be joined, counted, validated, or
used to compute what was left out. The requirement is that any claim at any level
traces to specific PRs through queryable structure.

## Decision

- Atomic level: `pr_summaries` → `pr_claims` → `pr_claim_evidence`. Evidence rows point at
  a file path (optionally a hunk), a quoted span of the description, a review comment, or
  a commit. Every evidence pointer is validated against the stored snapshot before the
  summary is stored.
- Aggregate level: `aggregate_summaries` → `aggregate_claims` → `aggregate_claim_sources`.
  A source is either a `pr_claim` or a child `aggregate_claim` (for reduction trees).
  Exactly one foreign key is non-null, enforced by a `CHECK` constraint.
- Input sets are stored (`aggregate_inputs`) so coverage (cited vs. uncited inputs) is a
  join, not an estimate.
- The model never sees or emits database ids. It is given short opaque tokens per call
  and emits those; the system maps tokens back to ids and rejects unknown ones.

## Rejected

- Free-text citations parsed by regex after the fact. Fragile, and gives the model a
  way to cite something that does not exist.
- A generic `references(from_type, from_id, to_type, to_id)` table. Compact, but the
  database cannot enforce that the referenced row exists.

## Consequences

- Drill-down is a recursive query over `aggregate_claim_sources`, then a join to
  `pr_claim_evidence`, then to `pr_files`.
- The extra tables cost nothing at this scale and make the "what was not mentioned"
  report trivial.
- A future compliance "finding" is the same shape as a claim: a statement with evidence
  against a PR snapshot. Nothing here forecloses that.
