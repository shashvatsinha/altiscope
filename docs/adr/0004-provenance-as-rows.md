# ADR-0004: Store evidence links in relational tables

Status: proposed

## Context

Provenance links a statement to its sources. Storing those links in tables lets queries
follow them, check that referenced records exist, and identify uncited inputs. Citations
stored only as prose would need parsing before those checks.

## Decision

- For one pull request, use `pr_summaries` → `pr_claims` → `pr_claim_evidence`.
  Evidence can identify a file, a diff hunk, quoted source text, a comment, or a commit.
  Validate references against the saved snapshot before storing the summary.
- For combined summaries, use `aggregate_summaries` → `aggregate_claims` →
  `aggregate_claim_sources`. Each source refers to a `pr_claim` or a child
  `aggregate_claim`. A `CHECK` constraint requires exactly one source foreign key.
- Record input sets in `aggregate_inputs` to identify cited and uncited inputs.
- Give the model short per-call tokens for references that map to database IDs.
  Resolve those tokens in code and reject unknown ones.

## Alternatives considered

- **Parse free-text citations after generation.** This adds parsing rules and still
  requires checking each reference against the source material.
- **A generic `references(from_type, from_id, to_type, to_id)` table.** This is compact,
  but ordinary foreign keys cannot enforce references to several possible tables.

## Consequences

- Evidence exploration would follow `aggregate_claim_sources` recursively, then
  `pr_claim_evidence` and the relevant snapshot records, including `pr_files`.
- Separate tables allow queries to identify cited and uncited inputs. They add joins
  and storage work.
- A future finding about a change could use the same statement-and-evidence structure.
  Such analysis remains outside the first version.

The schema and reference checkers exist; saving results and exploring their evidence
remain unbuilt. Reference checks establish membership in the source material, not
whether that material supports the statement.
