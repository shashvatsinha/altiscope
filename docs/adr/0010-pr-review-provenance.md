# ADR-0010: Save an overall PR report with its source and generation history

Status: accepted

Replaces [ADR-0009](0009-m1-publication-contract.md) and the mandatory sentence-level
citations and assessment in [ADR-0007](0007-accuracy-over-breadth.md).
[ADR-0011](0011-aggregate-report-provenance.md) extends this approach to combined reports.

## Why

M1 should explain a merged PR in a useful code-based report. A reader who wants to
check the explanation can open the PR. Requiring the model to attach evidence to
every statement adds complexity without establishing that the explanation is correct.

## Decision

Generate one overall review from the saved PR. Show code patches before PR prose;
the description supplies context but may not accurately describe the final changes.
Code attaches the saved source version and the model-call record to the report.
The model does not generate sentence-level citations. Per-claim assessment is not planned.

Save and display usable output after checking its format and nonblank text. Allow one
replacement attempt for malformed output. Withhold refused, truncated, or failed
responses. A failed rerun leaves the previous usable report current.

Show input exclusions so readers know which material the model did not see. The CLI
labels interpretation as unverified. A later model may assess an overall report;
that is separate from this decision. Prompts continue to prohibit judgments about people.

## Storage and compatibility

Store report text in the existing summary table, linked to its PR snapshot, prompt,
and model call. Keep earlier generated versions. No new claim or citation rows are
needed. Historical prompt files remain unchanged.

This decision did not require a reader for obsolete claim-format development reports.
It does require preserving active overall PR reports and their source and generation
history when changing the database.

## Deferred database cleanup

At acceptance, unused claim tables were left in place for a separate migration.
Migration 0004 subsequently removed the obsolete PR claim tables. Some aggregate
claim and assessment tables remain as legacy structures; they are not the storage
design for current reports.

When replacing those remaining structures, inspect their foreign keys, indexes,
uniqueness rules, and checks. The original dependencies in migration 0001 were:

- `pr_claim_evidence` linked to `pr_claims`.
- `aggregate_claim_sources`, `verifications`, and `flags` also linked to PR claims.
- Aggregate source rows had checks requiring exactly one source type.

Use the current schema as the starting point and a new numbered migration for each
change. Do not rewrite applied migrations or use a broad `DROP ... CASCADE`. Preserve
active report text, snapshot and model-call links, saved facts, and input manifests.
Any future independent assessment should target a whole report.

## Validation

Test collection, generation, storage, and inspection together. Check that the saved
report points to the correct source, prompt, and model call, and that failed reruns
preserve existing reports. Database changes need both fresh-setup and upgrade tests.
Human review of generated text is still needed to assess usefulness and accuracy.
