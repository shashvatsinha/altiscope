# M3 workflow walkthrough

Status: the credential-free workflow and 20-source preparation are repeatable.
The live OpenRouter run, owner inspection, and release are pending. See the
[execution plan](evaluation/m3-workflow-plan.md) for exact local IDs, call
estimate, and remaining steps. [ADR-0013](adr/0013-m3-workflow-release-scope.md)
defines the workflow demonstration's claim boundary.

## Set up

From the repository root, install the locked environment, start Postgres, set a
database URL, and apply append-only migrations:

```bash
uv sync --extra dev --frozen
docker compose up -d db
export ALTISCOPE_DATABASE_URL='postgresql://altiscope:altiscope@localhost:5432/altiscope'
uv run altiscope db migrate
```

Use a separate database if preserving an existing Altiscope installation.
Comparison runs save new versions and do not replace production-current reports.
No model credential is needed for the next section.

## Credential-free PR and aggregate demonstration

```bash
uv run python examples/m3/synthetic_study.py
```

The script prints two comparison invocation IDs, one for a synthetic PR and
one for a manager aggregate over one exact saved synthetic PR report. Each
invocation contains two generation recipes and their prompt-only baselines.
It also prints a whole-result `disagree` assessment ID and a simulated review
session ID. These responses and judgments are hand-authored fixtures. They
demonstrate persistence, inspection, exposure order, and export; they are not
model or human quality results.

Use the printed IDs to inspect both kinds of saved source and export the
simulated review:

```bash
uv run altiscope show-comparison PR_INVOCATION_UUID
uv run altiscope show-comparison AGGREGATE_INVOCATION_UUID --verbose
uv run altiscope show-comparison PR_INVOCATION_UUID \
  --review-session SIMULATED_REVIEW_SESSION_UUID
uv run altiscope reviews export SIMULATED_REVIEW_SESSION_UUID \
  --output /tmp/m3-synthetic-review.json
```

Without `--review-session`, the inspection command hides the assessor verdict
and rationale. The exact session reveals only assessments with a saved exposure
event. The export includes initial judgment, exposure, observation, and explicit
unavailable effort values. The synthetic session is marked complete; its reviewer
ID begins `synthetic-`.

For an offline pilot on one selected **real** development source, collect PR
#19 once, then run the same fixture-backed sequence:

```bash
uv run altiscope ingest microsoft/markitdown 19
uv run python examples/m3/synthetic_study.py --pilot-pr19
```

The pilot's response deliberately makes an unsupported HTML-detection claim
so the recorded assessor can disagree. This checks the workflow, not a live
model. It does not create a qualified human review.

## Prepare the full 20-source operational run

The owner chose all 20 selected PRs and one manager aggregate for the release
workflow demonstration. The later quality study needs new held-out cases after
these outputs are exposed. Collection and freezing perform no model calls:

```bash
uv run python examples/m3/collect_selected_prs.py
uv run python examples/m3/freeze_selected_sources.py
uv run python examples/m3/prepare_openrouter_demo.py
```

`collect_selected_prs.py` uses `ALTISCOPE_GITHUB_TOKEN` or the authenticated
GitHub CLI token. It prints source IDs, not held-out content. The next script
prints source IDs, hashes, and estimated sizes. Save that output as the run's
source inventory. The recipe script prints immutable recipe IDs and hashes;
each rerun appends new versions, so use the exact IDs from one run. The
checked-in [20-source inventory](evaluation/m3-workflow-sources-v1.json) and
[plan](evaluation/m3-workflow-plan.md) identify the prepared local run.

Live calls require an approved spend cap and an OpenRouter key. The plan lists
the exact recipe IDs and resumable runner commands. Its default mode makes no
calls; `--execute` runs a selected paid stage after cap approval. It records
progress after every case and checks a conservative next-case cost ceiling
against saved OpenRouter spend. Eight successful saved PR reports
for the held-out window must be generated and passed in dataset order to
`examples/m3/freeze_openrouter_aggregate.py`; it checks every report against
the frozen snapshot ID. `examples/m3/freeze_workflow_spec.py` then retains the
exact aggregate inputs, source and recipe content, hashes, and approved cap
before comparisons run. The aggregate comparison runs on that one frozen
source. Assessments remain optional records attached to exact successful
candidate results.

## Validation and interpretation

Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`,
and `uv run pytest`. With Postgres configured, `uv run pytest -o addopts='' -q`
runs the full integration suite. The recorded checkpoint passed 220 tests with
Postgres. M1/M2 fixture demos also remain runnable:

```bash
uv run altiscope demo --stage pr_summary
uv run altiscope demo --stage aggregate --altitude manager
```

The real operational run can show outputs, failures, usage, latency, cost,
comparison history, and review/export function. Without qualified reviewers,
it cannot show correctness rates, reader usefulness, error-detection rates,
or manual effort savings. Owner acceptance of workflow behavior and examples
should be recorded separately from source-quality judgments.
