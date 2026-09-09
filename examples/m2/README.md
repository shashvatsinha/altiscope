# A synthetic billing repository

Four fictional PRs add billing retries, event deduplication, failure diagnostics,
and tests. [repository.json](repository.json) contains the saved source examples and
hand-authored PR reports. The `ic`, `manager`, and `exec` JSON files contain recorded
aggregate responses; `children.json` supplies the two intermediate responses used
in the small-context demo.

Read the same work at different levels:

- [Engineer report](sample-ic.txt): mechanisms and implementation limits.
- [Manager report](sample-manager.txt): delivered capabilities and delivery limits.
- [Executive report](sample-exec.txt): a shorter account of the capabilities.
- [Multi-level manager report](sample-multilevel.txt): the same final text reached
  through two intermediate reports, with all original PR links retained.

Run `uv run altiscope demo --stage aggregate --altitude manager`. Add `--multi-level`
to exercise a summary tree and `--persist` to save report versions in Postgres and
follow their printed drill-down commands. See the [walkthrough](../../docs/M2-WALKTHROUGH.md).

## Review record

Prepared and inspected by the implementing agent on 2026-09-08. The examples consistently
separate code behavior from unmeasured production outcomes. The engineer view describes
transactional intake and retry behavior; the manager view summarizes capabilities.
Both retain the limitations and the same four underlying PR links.

These are hand-authored synthetic fixtures. Agent inspection and passing replay tests
are not human review or evidence of live model quality. Owner review of the samples
has been requested and is pending. No human review is claimed yet.
