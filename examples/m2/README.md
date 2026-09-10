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

These are hand-authored synthetic fixtures, not evidence of live model quality.
On 2026-09-10, after being asked whether the engineer and manager samples were suitable
to ship, the owner instructed: “Yes, check in these two files.” Both files were already
tracked and are retained unchanged. This records acceptance for inclusion in M2, not
a claim of a separate formal review or validation of real-world model accuracy.
See the [release evidence](../../docs/releases/m2.md) for the separate smoke-test record.
