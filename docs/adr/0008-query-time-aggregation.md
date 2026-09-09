# ADR-0008: Combine reports when a reader requests them

Status: proposed; input and version rules updated by [ADR-0011](0011-aggregate-report-provenance.md).

## Why

Readers may ask for any date range. A month with a few PRs can fit into one model
request; a busy year may not. Altiscope needs to combine reports without assuming
that every request fits in one call.

## Decision

Use one call if the input reports fit the model's budget. Otherwise, sort them in a
stable order and split them into groups that fit. Summarize each group, then summarize
those results. Repeat until one report remains. This is a summary tree: the original
PR reports are at the bottom and the requested summary is at the top.

A request specifies the sources, dates, and reader's level of detail. Topic filters
and team membership at merge time are later extensions. Build reports on request
rather than generating fixed weekly or monthly rollups on a schedule.

Reuse a saved result when its exact input versions and generation settings match.
ADR-0011 defines preservation of old versions, latest-input defaults, and explicit
updates. Each report links to all its immediate inputs and all underlying PRs.

## Earlier proposal

This ADR originally proposed linking individual statements to statements in child
reports and measuring cited-input coverage. ADR-0011 replaces both: the application
records the supplied reports directly, and there is no coverage score.

## Alternatives considered

- **Scheduled weekly or monthly summaries:** reusable, but fixed periods do not match
  every requested date range.
- **Retrieve only selected inputs for one call:** reduces input size, but can exclude
  relevant work. This is not the initial approach to a repository/date window.

## Consequences and status

Several calls take longer and may lose meaning as summaries get shorter. Planning
estimates intermediate sizes; execution must check the actual text before each call.
If a single input cannot fit, or two child reports cannot be combined, planning fails.

Grouping, full tree execution, aggregate storage, cache lookup, latest-version
resolution, and CLI inspection are implemented in M2. See the
[walkthrough](../M2-WALKTHROUGH.md) for a repeatable example.
