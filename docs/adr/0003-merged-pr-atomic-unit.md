# ADR-0003: Summarize one merged pull request at a time

Status: proposed; partly superseded (see below).

Version and cache rules are now defined in [ADR-0011](0011-aggregate-report-provenance.md). New reports use the latest successful inputs; old reports keep their original inputs.

## Context

A pull request brings together a code change, its description, and review discussion.
Individual commits may contain partial work or fixups. Merge time provides a date for
placing the completed change in a report.

## Decision

- Produce an atomic summary—a summary of one pull request—only after merge. Cache it
  until the prompt, schema, or model changes.
- Ingest open and closed-unmerged pull requests for facts such as counts and ages,
  without summarizing them in the first version.
- Use merge time to place a pull request in a query window.

## Unresolved details

Descriptions and comments can change after merge. The original cache rule above does
not cover those edits. The [architecture](../ARCHITECTURE.md#6-keeping-results-traceable)
requires new results when source material changes; source refresh and cache invalidation
need to be reconciled when the storage workflow is implemented.

Open and abandoned work would appear as facts, without descriptions of the work.
Summarizing it would require a refresh rule as the pull request changes. This remains
an [open question](../ARCHITECTURE.md#10-open-questions).

## Consequences

- Squash, merge-commit, and rebase merges use the same source: the pull request.
- Direct pushes that bypass pull requests are outside this view. A later version could
  report how many commits in the window have no associated pull request.
