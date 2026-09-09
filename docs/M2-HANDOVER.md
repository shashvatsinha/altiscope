# M2 handover for the next Codex session

Prepared 2026-09-08. This is a session handover, not a milestone completion report.

## Current implementation update

The owner approved the simplified documents and directed completion of M2. The code
now includes migration 0005, shared model-call storage, bottom-up execution, exact input
version links, caching, GitHub refresh/local-only resolution, aggregate/show-aggregate/
show-report CLI commands, and synthetic single- and multi-level demos.

Read [M2-WALKTHROUGH.md](M2-WALKTHROUGH.md), [release evidence](releases/m2.md), and
current [ADR-0011](adr/0011-aggregate-report-provenance.md). The earlier session notes
below are historical, including their list of missing components and coverage rules.
The latest full database-backed run passed 124 tests. Human sample review has been
requested. Main merge and release tagging have not occurred.

## Update after owner review (2026-09-08)

The owner has now clarified the direction in [ADR-0011](adr/0011-aggregate-report-provenance.md).
The application records all supplied report versions and PR links; the model only
summarizes. Model-selected references and coverage are removed in schema/prompt v4.
Preserve every generated version and model/prompt history. New summaries use the
latest successful reports below them. Existing summaries keep their original inputs
and only update on request. Manual version selection is future work.

The sections below describe the earlier session and are historical where they discuss
v3 references, coverage, or the earlier wording of ADR-0011. Use ADR-0011 and the current architecture for
implementation guidance. Aggregate persistence and full execution remain outstanding.

Validation after this correction: 104 tests passed with local Postgres enabled;
strict pyright, Ruff lint/format checks, and git diff --check passed. The new
regression exercises input/link retention across composed single-node calls, not
database version resolution or end-to-end aggregate execution. No live model calls
were used. The earlier validation count below belongs to the previous session.

## Start with the owner's review feedback

The owner is ending this session to review the changes and will start a fresh session
with requested revisions. Address that feedback first. Do not automatically proceed
with issue #28 or treat the existing implementation as immune to revision.
The owner authorized the foundation corrections and then requested their commit;
they have not yet completed their review of the resulting code or approved an M2 release.
ADR-0011's accepted status records authorization of the direction, not final code review.

Read CLAUDE.md, docs/ARCHITECTURE.md, README.md, THESIS.md, and ADR-0010/0011 before
substantive changes. Inspect current git status and diffs: this document describes a
point in time, and the owner may have made edits since it was written.

## Git state and scope

Repository: /Users/shashvat/Work/altiscope
Branch: feat/m2-report-contract

Implementation commits:
- 828f4ef — Fix M2 collection and budgeting; adopt report-level provenance (Codex).
- 0cb7c1c — Implement date-window repository PR resolution and ingestion (Gemini).
- 73993f8 — Implement aggregate provenance migration and 3-altitude schema v2 (Gemini).

The working tree was clean after 828f4ef. That commit was not pushed. No PR was opened,
no issues were changed or closed, and nothing was merged to main by this Codex session.
This handover document was created afterward. Recheck its git status on resumption.

Gemini's uncommitted planner/coverage/test changes were reviewed and incorporated into
828f4ef, with corrections. Do not restore them from the original summary.

## What changed and why

1. GitHub collection: `_get` now merges pagination into existing URL parameters.
   Previously HTTPX replaced state=closed, sort=updated, and direction=desc with
   pagination parameters, breaking the assumptions behind date-window collection.
   Exhausting 100 pages now raises CollectionError instead of returning partial data.
   Duplicate PR numbers are removed while retaining merge-time/number ordering.
   Remote and local window lookup reject reversed dates; timestamp bounds are inclusive.

2. Budgeting: the planner no longer manufactures a minimum 1,000-token budget when
   reservations exhaust context capacity. It counts schema costs and validates token
   settings. Execution of a single node checks the rendered system/user/schema request
   plus envelope allowance before every call, including the repair call.

3. Aggregate contract: schema version 3 replaces claims with headline, narrative,
   sections (heading/text), and one report-level sources list of original PR tokens.
   Tokens are normalized to a sorted unique list. Text fields reject blank content.
   Three altitudes remain ic, manager, exec, with the existing friendly aliases.
   Prompt v3 was added; historical v1/v2 prompt files were preserved.

4. Validation: unknown report navigation tokens reject the complete output. The old
   validator selectively trimmed claims while leaving narrative untouched. There is
   no per-claim citation requirement or semantic assessment. A report with an empty
   sources list remains usable output, with zero coverage for a nonempty window.

5. Coverage: compute against the original PR token set and the final report references.
   At a parent node, allowed references must be the union of tokens retained by child
   reports, not the union of all inputs supplied to those children. Earlier omissions
   therefore cannot be silently restored. Never expand a cited child ID to all its PRs.
   Coverage discloses citation presence, not semantic completeness or verified accuracy.
   Empty input coverage is 1.0 by convention; the future service should bypass generation
   for an empty window.

6. Single-node generation: generate_aggregate uses the existing Provider interface and
   GenerationResult, records attempt timestamps/results/errors, allows at most one
   replacement for malformed output, and withholds output on refusal, truncation,
   transport failure, or other terminal outcomes. No vendor SDK imports were added.

7. Migration tests: fresh schema and populated M1 upgrade are tested in isolated schemas.
   The upgrade checks preserved PR summaries, snapshots, model calls, prompt records,
   saved facts, and manifests. Existing migration SQL was not edited.

## Files to inspect

- src/altiscope/ingest/github/pat.py
- src/altiscope/store/snapshots.py
- src/altiscope/schemas/aggregate.py
- src/altiscope/aggregate/planner.py
- src/altiscope/aggregate/coverage.py
- src/altiscope/aggregate/validate.py
- src/altiscope/aggregate/generate.py
- prompts/aggregate/v3.md
- tests/test_aggregate.py
- tests/test_aggregate_generation.py
- tests/test_pat_client.py
- tests/test_migrations.py
- docs/adr/0011-aggregate-report-provenance.md
- docs/ARCHITECTURE.md, section 11

Use `git show 828f4ef` for the exact implementation change.

## Validation and reproduction

Last completed full run: 105 tests passed with local Postgres enabled. Ruff lint,
format checks, strict pyright, and git diff --check also passed. No live paid model
calls or live GitHub ingestion were used to validate this correction; HTTP and model
responses are mocked/recorded fixtures. Test success does not establish report quality.

From the repository root, using the existing .venv:

```bash
# Focused checks; no model credentials or database needed.
.venv/bin/pytest -v tests/test_aggregate.py tests/test_aggregate_generation.py tests/test_pat_client.py

# Full suite against the local development database, which must be running.
ALTISCOPE_DATABASE_URL='postgresql://altiscope:altiscope@localhost:5432/altiscope' \
  .venv/bin/pytest -o addopts='' -q

.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pyright --pythonpath .venv/bin/python
git diff --check
```

Without ALTISCOPE_DATABASE_URL, database checks are skipped. Database tests write
fixture data; use the development/test database. The migration preservation tests
create and remove their own randomly named schemas.

Plain pyright initially picked the wrong interpreter and reported missing dependencies;
explicit --pythonpath .venv/bin/python resolved that. Localhost database connections
and writes to .git required sandbox escalation. Follow the actual current permission
rules rather than interpreting a sandbox denial as a code failure.

## Remaining work and limits

Parent milestone: https://github.com/shashvatsinha/altiscope/issues/5
Children #24 through #30 were all open when inspected. Gemini's claim that Tasks 1–4
were complete was too broad. Do not close them solely on this handover's test count.

The parent issue's accepted PR-level provenance direction conflicted with child #25's
claim-citation requirements. This implementation follows the parent and ADR-0010,
with the rationale recorded in ADR-0011. GitHub issue text has not been reconciled yet.

After addressing the owner's review, the next implementation work is:

- #28: bottom-up tree execution, configured aggregate routing, deterministic input hashes,
  zero-call cache hits, invalidation on source/review changes, atomic storage of reports,
  input mappings, original-PR coverage and call provenance. Failures must preserve an
  existing valid publication. Reuse M1 services and provider conventions.
- #29: aggregate/show-aggregate CLI, window resolution and missing ingestion/review
  generation, altitude selection, empty-window handling and source navigation.
- #30: examples/m2 credential-free demo, contrasting altitude sample reports, human
  review, walkthrough, architecture/roadmap updates and release evidence.

There is no aggregate CLI, persisted aggregate, cache, or complete tree execution yet.
The multi-level coverage regression composes the helpers; it does not demonstrate
end-to-end tree execution. The future service must actually enforce each parent's
allowed reference set and recheck real child output sizes, which planning only estimates.

Local snapshot presence alone does not establish a complete or fresh remote window.
The resolver still needs a deliberate source refresh policy so changed sources can
invalidate cache entries. Provider-neutral estimates are not exact token counts.

Migration 0004 retains legacy aggregate-claim/assessment structures. They are not the
v3 storage contract; #28 needs a new append-only migration. The preservation tests
cover active M1 review data, not arbitrary populated obsolete claim-based accounts.
No permission to delete unrelated historical data should be inferred from these tests.

Keep main at a completed demonstrable milestone. The milestone workflow uses an
integration branch and focused implementation PRs; inspect current remote branches
before choosing a PR target. No integration branch was created by this session.
Do not merge or release incomplete M2 based on component test success.
