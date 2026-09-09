# M2 handover

Prepared 2026-09-09 for the next Codex session.

## Start here

Repository: `/Users/shashvat/Work/altiscope`

Current branch: `feat/m2-report-contract`

M2 implementation commit: `9469700` — Complete M2 report execution, history,
CLI and demos.

The branch has no configured upstream and was not pushed by the last session. A push
was attempted, but the user stopped it. Do not assume any remote branch or pull request
was created. Check the current local and remote state before publishing anything.

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

The final database-backed run on 2026-09-08 passed all 124 tests:

```bash
ALTISCOPE_DATABASE_URL='postgresql://altiscope:altiscope@localhost:5432/altiscope' \
  .venv/bin/pytest -o addopts='' -q
```

Ruff lint, Ruff format checking, strict pyright, `git diff --check`, and local Markdown
link checks also passed. The tests cover:

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

Implementation and repeatable demos are ready for owner review. The owner has not yet
approved the engineer and manager sample reports in `examples/m2/`, although review was
requested. Do not mark the sample as human-reviewed until that approval is explicit.

No M2 pull request, integration merge, main merge, release tag, or issue closure was
completed by the last session. GitHub issues #24–#30 and parent #5 may still contain
the superseded coverage/citation wording. Reconcile those descriptions with ADR-0011
before treating their old acceptance text as current product direction.

The next session should begin with owner review feedback. If the implementation is
accepted, inspect remote branches, push the feature and M2 integration branches as
appropriate, open a focused draft PR against the M2 integration branch, and let CI and
repository review complete before any merge, issue closure, or release tag.

Known limits that do not block this implementation review:

- GitHub cannot provide a transactionally simultaneous snapshot of an entire repository.
- Token counts are provider-neutral estimates.
- Execution is synchronous; there is no durable background queue or crash recovery.
- Concurrent identical requests can both generate results; both versions are retained.
- Manual input-version selection and report comparison UI are future work.
