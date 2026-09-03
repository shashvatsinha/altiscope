# ADR-0008: Aggregation is on demand with a query-time reduction tree

Status: proposed

## Context

Higher-level views must be generated at query time from atomic summaries in an arbitrary
window. There are no scheduled weekly or quarterly rollups. A large team over a long
window can have thousands of atomic summaries, which exceeds any model's context.

## Decision

- A query names subjects, a window, an altitude and (later) a lens. The input set is
  resolved from the database and recorded.
- If the input set fits the routed model's budget, one call produces the aggregate.
- Otherwise the planner partitions the inputs deterministically (by merge time, then
  subject) into groups that fit, produces one child aggregate per group, and recurses
  until a single parent remains. Children are stored aggregates with their own claims and
  sources; the parent's claims cite child claims. Drill-down traverses the tree.
- Results are cached by hash of the sorted input set, altitude, lens, prompt version and
  model. A cache hit is the same on-demand answer to the same question; nothing is
  computed before it is asked for.
- Team membership is resolved as of each PR's merge date.

## Rejected

- Fixed calendar rollups (week → month → quarter). Cheaper, but they impose a
  granularity the reader did not ask for and hide which PRs are behind a quarter's
  sentence unless the rollup chain is itself stored with provenance, at which point it is
  this design with worse cache keys.
- Embedding retrieval over summaries to fit a window into one prompt. Reintroduces
  selective emphasis by construction: whatever retrieval does not return is silently
  absent.

## Consequences

- Latency for large windows is a tree of calls, run in parallel per level. Acceptable
  for a reporting tool; a progress indicator is needed in the UI.
- Coverage is computed at every level, so a leaf that omits PRs is visible even if the
  parent cites the leaf.
