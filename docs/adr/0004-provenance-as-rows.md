# ADR-0004: Store source relationships in database tables

Status: proposed; claim-level links replaced by [ADR-0010](0010-pr-review-provenance.md)
and [ADR-0011](0011-aggregate-report-provenance.md).

## Why

When a reader opens the inputs to a report, the application should be able to load
those records directly. Saving relationships in database tables allows that lookup
and lets the database check that linked records exist. Links embedded only in prose
would need parsing and could be missing or malformed.

## Original proposal

The first design split reports into individual claims. Each PR claim linked to files,
patches, comments, or commits. Each combined-report claim linked to claims in reports
below it. The model returned short labels that code translated into database IDs.

This required several claim and evidence tables. It could check whether a referenced
source existed, but could not establish whether the source supported the statement.

## Current direction

ADR-0010 and ADR-0011 replace the claim structure. A PR report links to its saved PR
snapshot and generation history. A combined report links to every input report version.
The application knows these inputs and records them without asking the model to choose.
Readers can follow those relationships down to GitHub PR links.

The general choice of relational links remains useful. The old claim tables are not
a requirement for new work. Follow ADR-0011 and the current migrations when designing
aggregate storage.

## Alternatives considered

- **Parse links from generated text:** depends on the model's formatting and selection.
- **One generic table for every relationship type:** fewer tables, but ordinary foreign
  keys cannot check a reference that may point to several different tables.

## Tradeoff

Explicit relationships add tables and queries. They earn their place by supporting
source inspection and preserving exactly what an older report used.
