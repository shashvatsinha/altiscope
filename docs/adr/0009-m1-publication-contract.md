# ADR-0009: Publish citation-valid claims with explicit unverified interpretation

Status: proposed

## Context

Milestone 1 (#4, #11) permits an unverified account. The v1 output has unrestricted
headline, narrative, discrepancies and uncertainties that could survive invalid claims.

## Decision

For M1, supersede ADR-0007's mandatory second-model review and free narrative with a
v2 claims-only output. Keep v1 schema and prompt files for historical readability.
Display only the complete citation-valid claim set, source excerpts, computed facts
and input omissions. Label semantic interpretation `unverified`, never `verified`.
Citation validation establishes source membership, not support for the claim's meaning.

Invalid shape or evidence permits one complete replacement attempt. If it remains
invalid, retain attempts with `needs_review` and publish no generated text. Refusal,
truncation and transport failure are not evidence repair. Language warnings also withhold
publication pending review. Never drop a bad claim and publish the remainder.
A future semantic verifier must record its own per-claim verdicts; it cannot infer
verification from citation validity.

Quotes match case-sensitively after whitespace collapse; blank quotes fail. Commit
prefixes are hexadecimal, at least seven characters and unique among shown commits.
Hunks must match a syntactically valid complete header line. Comment identity is the
pair of comment kind and GitHub ID, mapped to opaque input tokens.

## Consequences

The first report is a short list of checkable statements, not polished narrative.
Unsupported interpretation can still pass pointer checks. Expose this limitation beside
every account. Sophisticated narrative reconciliation and semantic review wait for M3.
