# M2 handover

Updated 2026-09-10 after the three code-review fixes.

## Start here

Integration branch: `feat/m2-report-contract`.

Verified integration commit: `7d71aaa`, the merge of PR #37. PRs #35 and #36
are also merged into this branch. Issues #31, #32, and #33 are closed.
The remote integration branch exists. M2 is not merged into `main` or released.

Read these files before changing M2:

- [Architecture](ARCHITECTURE.md)
- [ADR-0011](adr/0011-aggregate-report-provenance.md)
- [M2 walkthrough](M2-WALKTHROUGH.md)
- [M2 release evidence](releases/m2.md)
- [M2 example and review record](../examples/m2/README.md)

## Product decision made during owner review

Provenance has a narrow, practical meaning in M2. The model summarizes the reports
it receives. The application records every supplied report version and derives the
complete list of underlying GitHub PR links itself.

There are no model-selected source references, per-sentence citations, or coverage
percentages. Those mechanisms were removed because the application already knows its
inputs and a citation count does not measure the accuracy or usefulness of a summary.

Every generated version is preserved with its source or immediate input reports,
model, prompt, settings, attempts, and generation time. A new higher-level summary
uses the latest successful reports from the level below. Existing summaries retain
their original inputs and never regenerate automatically. Manual version selection
is future work.

ADR-0011 was corrected in place because it was created on this unmerged branch. Do
not create an ADR-0012 for this correction.

## What M2 implements

M2 now supports the complete repository-summary path:

1. Resolve merged PRs in an inclusive UTC date window.
2. Refresh selected PRs from GitHub by default, or use saved snapshots with
   `--local-only`.
3. Reuse the latest successful PR report for each current snapshot, generating a
   missing report through the M1 service.
4. Select an `ic`, `manager`, or `exec` level of detail.
5. Generate one aggregate when inputs fit, or execute a deterministic reduction tree
   from the bottom up when they do not.
6. Check the fully rendered request before every model call, including repair calls
   and parent calls containing actual child output.
7. Cache each node by its exact input versions and text, source hashes, query, prompt,
   schema, model, and generation settings.
8. Save aggregate versions, exact input relationships, and model-call history in
   Postgres. Failed attempts and earlier successful versions remain available.
9. Inspect aggregates and historical PR reports through CLI drill-down commands.
10. Reproduce single-level, multi-level, and three-altitude behavior with synthetic,
    credential-free fixtures.

Important implementation files:

- `src/altiscope/aggregate/service.py`: routing, tree execution, cache keys, and reruns.
- `src/altiscope/aggregate/resolve.py`: remote refresh, local resolution, and latest
  successful PR report selection.
- `src/altiscope/aggregate/inputs.py`: exact report inputs and deterministic PR links.
- `src/altiscope/store/aggregates.py`: aggregate versions, input edges, and call links.
- `src/altiscope/store/calls.py`: model-call persistence shared by M1 and M2.
- `src/altiscope/cli/main.py`: aggregate, inspection, and demo commands.
- `migrations/0005_report_versions.sql`: current aggregate report storage.
- `prompts/aggregate/v4.md`: current aggregate prompt and schema contract.

Legacy aggregate-claim tables remain in earlier migrations for database history. The
current report design does not use them. Never edit an applied migration.

## CLI reproduction

From the repository root, install locked development dependencies:

```bash
uv sync --extra dev --frozen
```

Run the fastest credential-free test:

```bash
uv run altiscope demo --stage aggregate --altitude manager
```

Compare the three reader levels:

```bash
uv run altiscope demo --stage aggregate --altitude ic
uv run altiscope demo --stage aggregate --altitude manager
uv run altiscope demo --stage aggregate --altitude exec
```

Exercise the summary tree. It should report three aggregate model calls on the first
request and zero on its repeated cache check:

```bash
uv run altiscope demo --stage aggregate --altitude manager --multi-level
```

Exercise Postgres storage and drill-down:

```bash
docker compose up -d db
uv run altiscope db migrate
uv run altiscope demo --stage aggregate --altitude manager --multi-level --persist
```

The persisted demo prints a root report ID. Follow the commands it prints:

```bash
uv run altiscope show-aggregate REPORT_ID --verbose
uv run altiscope show-aggregate CHILD_REPORT_ID
uv run altiscope show-report PR_REPORT_ID --verbose
```

The root should lead to two intermediate reports, which lead to four historical PR
reports and their GitHub URLs.

For a live public repository, configure a model and optionally a GitHub token:

```bash
export ALTISCOPE_MODELS_CONFIG=config/examples/m1.yaml
export OPENROUTER_API_KEY=YOUR_KEY
# Optional for higher GitHub API limits:
export ALTISCOPE_GITHUB_TOKEN=YOUR_TOKEN

uv run altiscope aggregate owner/repository \
  --since 2026-06-01 --until 2026-06-30 --altitude manager
```

This refreshes GitHub before cache lookup and may incur model charges. To operate only
on saved snapshots, add `--local-only`. To bypass aggregate caches while keeping old
versions, add `--regenerate`.

## Validation evidence

The 2026-09-10 Postgres-backed suite passed all 175 tests with no skips.
See [release evidence](releases/m2.md) for exact commands and separate CI records.
The suite covers:

- Single-, multi-, and three-level aggregate execution.
- Zero-call cache hits.
- Cache changes after source, PR report, prompt, model, setting, or altitude changes.
- Empty windows with no model calls.
- Complete underlying PR lists independent of generated prose.
- Actual parent request sizing after child generation.
- One malformed-output repair and terminal failure behavior.
- Preservation of previous successful results after failed reruns.
- Transaction rollback for partial aggregate persistence.
- Fresh database setup and upgrade from populated M1 data.
- Persisted CLI drill-down from a root aggregate to all four PR reports.

No paid model calls or live GitHub ingestion were used for this validation. HTTP and
model behavior use controlled fixtures. The synthetic reports demonstrate the workflow;
they do not establish live model quality.

## Review and release state

The three code fixes are merged into the integration branch. Each PR's CI passed.
Those PRs have no submitted GitHub review records; merge evidence does not establish
sample approval. Parent #5 and implementation issues #24 through #30 remain open.
Issue #34 tracks this documentation reconciliation.

Human approval of the engineer and manager samples remains pending. See the
[sample review record](../examples/m2/README.md) and the separate smoke-test record
in [release evidence](releases/m2.md).

Next steps:

1. Review the focused documentation PR against `feat/m2-report-contract`.
2. Obtain explicit owner approval of the sample reports.
3. Complete milestone PR review, CI, and integration before the merge into `main`.
4. Close completed issues and create the release tag after the release requirements pass.
5. Record the resulting PR, commit, issue, and tag links in the release evidence.

Known limits that do not block this implementation review:

- GitHub cannot provide a transactionally simultaneous snapshot of an entire repository.
- Token counts are provider-neutral estimates.
- Execution is synchronous; there is no durable background queue or crash recovery.
- Concurrent identical requests can both generate results; both versions are retained.
- Manual input-version selection and report comparison UI are future work.
