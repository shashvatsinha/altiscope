# ADR-0003: The merged pull request is the atomic unit

Status: proposed

## Context

Commits are noisy (WIP, fixup, rebase rewrites) and rarely carry a coherent "why". A
merged PR is a stable, one-time event with a description, a diff, review discussion,
and a merge timestamp, which makes it both a natural unit of meaning and a natural cache
key.

## Decision

- Atomic summaries are produced only for merged PRs, once, and cached until the prompt,
  schema, or model changes.
- All PRs (open, closed-unmerged) are still ingested and stored, so facts such as
  "5 open PRs, oldest 19 days" and "2 PRs closed without merge" are available and
  honest. They are not summarized in v1.
- Merge time, not creation time, places a PR in a query window.

## Tension to be aware of

Merged-only summaries make in-flight and abandoned work invisible in narratives. A
manager asking "what is X working on right now" gets counts, not content. Summarizing
open PRs is feasible but breaks the one-time-event property (the PR keeps changing) and
would need its own invalidation rule. This is open question 1 in the architecture doc.

## Consequences

- Squash-merge, merge-commit and rebase-merge repositories are all handled the same way
  because the PR, not the resulting commit(s), is what is read.
- Direct pushes to the default branch that bypass PRs are invisible. This is a known
  limitation and should be reported as a fact per repository ("N commits on main not
  associated with any PR in the window") in a later iteration.
