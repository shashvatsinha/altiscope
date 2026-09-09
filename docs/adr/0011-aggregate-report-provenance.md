# ADR-0011: Aggregate report references and original-PR coverage

Status: accepted (owner authorized the foundation correction following review).

Supersedes the parent-claim-to-child-claim proposal in ADR-0008 and the aggregate
claim contract in schema/prompt v2. Applies ADR-0010's accepted provenance approach
to M2; it does not introduce per-claim assessment.

## Decision

Aggregate schema/prompt v3 contains a headline, narrative, sections with headings
and text, and one report-level list of original opaque PR tokens. Sections do not
require individual citations. The application maps the tokens to saved PR reviews
and immutable snapshots for navigation. The full supplied input set is separate
from the report's referenced subset. Reference presence does not prove support.

Each intermediate report retains original PR tokens. A parent may reference only
tokens retained by its children, never an intermediate node ID or an omitted PR.
Coverage is computed over the full original window and the final report references,
so both earlier and final-level omissions remain visible. A report with no references
has zero coverage for a nonempty input set; an empty window needs no model call.

Reject unknown navigation tokens as malformed output; never selectively trim prose
or claims. Allow at most one replacement attempt. Refusal, truncation and transport
failure are terminal. Check the complete request, including schema and any repair
instructions, before every call. These checks establish usable output and navigation,
not semantic accuracy. Interpretations remain unverified.

## Consequences and implementation boundary

Historical prompts remain unchanged. No published aggregate v2 compatibility reader
is introduced. Migration 0004 remains append-only; its residual aggregate-claim and
assessment scaffolding is not the v3 persistence contract. Issue #28 must introduce
report storage and report-to-review/child lineage in a new migration, without relying
on claim rows or disturbing M1 publications. Existing migrations are not rewritten.

The foundation includes single-node generation and repair, deterministic planning,
and original-PR reference coverage. Tree orchestration, route selection, cache
invalidation, atomic aggregate persistence, CLI and the M2 demo remain subsequent work.
