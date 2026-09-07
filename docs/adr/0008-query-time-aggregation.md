# ADR-0008: Build reports on demand through a summary tree

Status: proposed

## Context

Readers choose their own date ranges. A large selection of pull request summaries may
exceed the chosen model's input budget. Combining groups of summaries in stages allows
larger reports while retaining links through the intermediate results.

## Decision

- A query specifies subjects, dates, altitude (level of detail), and later a lens
  (topic filter). Resolve and record its input set from the database.
- Use one model call when the inputs fit the selected model's budget.
- Otherwise, order inputs by merge time, subject, and ID, and divide them into groups
  that fit. Summarize each group, then combine those summaries, repeating until one
  report remains. Store intermediate summaries and have parent claims cite child claims.
  This forms a reduction tree that readers can follow back to individual changes.
- Cache results by a hash of the sorted input set, altitude, lens, prompt version, and
  model. Reuse matching results when requested; do not schedule calendar rollups.
- Resolve team membership at each pull request's merge date.

## Alternatives considered

- **Weekly, monthly, and quarterly rollups.** Could reuse scheduled work but would impose
  fixed periods on arbitrary date queries. Evidence links through each level would
  still need storage.
- **Embedding retrieval to select inputs for one call.** Would omit inputs based on
  retrieval relevance. Those omissions would need accounting beyond the selected set.

## Consequences

- Large reports require several calls, adding latency and opportunities to lose meaning.
  Calls at the same level could run in parallel. The UI would need progress reporting.
- Coverage at each level would let readers inspect uncited inputs in child summaries.
  Parent coverage alone does not show how much original work was represented.
- Planning uses estimates for intermediate output sizes. Inputs that cannot fit or a
  budget too small to combine children cause planning errors.

The planner and coverage calculation exist. Query resolution, execution of the planned
calls, caching, and the reader interface remain unbuilt.
