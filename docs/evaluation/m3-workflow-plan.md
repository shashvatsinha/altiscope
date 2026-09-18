# M3 workflow demonstration: preparation and handoff

Status on 2026-09-17: **offline pilot, synthetic demonstration, 20 public PR
collections, and source/recipe preparation complete; paid calls and owner review
pending.** This is release workflow evidence under
[ADR-0013](../adr/0013-m3-workflow-release-scope.md). The selected
[`m3-evaluation-v1`](m3-protocol-v1.md) confirmatory quality study remains
unrun and unfrozen. Held-out prepared text was hashed and saved without display;
the operational run will expose its outputs and retire those cases as untouched
holdouts for a later quality study.

## Scope and claim boundary

The owner requested the full selected
[`m3-markitdown-20-v1`](m3-eval-set-v1.md) set: 12 development PRs, eight
originally held-out PRs, and its one manager aggregate over those eight PRs in
the recorded order and inclusive 2025-05-21 UTC window. The repository's stable
GitHub ID is `888092115`. The aggregate is `single_step` over eight exact
successful saved PR-report versions. It tests composition over saved inputs,
not tree planning or the quality of earlier PR report generation. Upstream
generation time and cost are separate.
An authenticated GitHub search on 2026-09-17 again returned exactly those
eight PR numbers for the inclusive 2025-05-21 merge window.

There are two OpenRouter generation recipes per stage: Claude Sonnet 5 and Gemini
2.5 Flash, both using the current stage prompt with low effort and 4,096 reserved
output tokens. Each has a prompt-only baseline under the same model, endpoint,
schema, and settings. GPT-5.5 via OpenRouter is the independent whole-result
assessor with 2,048 reserved output tokens. These are mutable model aliases;
stored recipe configuration and returned model IDs describe the observed calls,
not a permanent model revision.

The owner will inspect functionality and saved examples. The owner has no
MarkItDown experience and will not make qualified source-level correctness
judgments. Therefore correctness, reader usefulness, correction effort,
assessment detection rates, and effort savings remain **unmeasured**. Synthetic
fixture judgments below are not included in any real quality result.

## Completed offline evidence

The isolated local database `altiscope_m3_issue50` received all migrations
`0001`–`0013` on a fresh Postgres 16 database. All 20 selected PRs were
collected under numeric repository ID `888092115`. An anonymous first collection
of #19 and #22 saved versions 1 (`3` and `4`); an authenticated refresh saved
versions 2 (`12` and `13`) because GitHub changed line-position metadata on
existing comments. The pilot used version 1. The operational source inventory
uses the exact version 2 snapshots. These IDs are local to this database.

The repeatable credential-free script is:

```bash
uv run python examples/m3/synthetic_study.py
uv run python examples/m3/synthetic_study.py --pilot-pr19
```

The first command uses the synthetic lock PR. The second uses the saved real
development PR #19, with **hand-authored** model responses and a simulated
reviewer. Both persist two candidates and their two baselines on a PR source and
a manager aggregate source, one independent `disagree` assessment, exposure,
post-assessment observation, and a review export. Both made zero network model
calls and incurred zero model spend. All mock effort is marked unavailable where
no timer ran. The #19 pilot exposed no workflow failure; its deliberately false
HTML-detection claim exercises the disagreement path. It does not count as human
review or real model quality evidence.

The #19 pilot saved PR comparison `7ff71a24-2211-40f3-a71d-77958bea7694`,
aggregate comparison `d0d81ee0-40bb-4964-a2f5-f440101ecf55`, assessment
`2c01e828-24a0-4f8a-8917-4cd73e2def30`, and simulated review session
`07a1cf22-8e27-42c9-ba41-c82ee2a94d7a`. `show-comparison --review-session`
rendered all four PR members, the assessment reveal, the simulated judgment,
and separately labeled usage/cost. `reviews export` wrote a complete JSON record
to `/private/tmp/m3-issue50-pilot-review.json`. These local IDs are pilot evidence,
not entries in the live run manifest.

Offline regression validation on 2026-09-17: `ruff check .`,
`ruff format --check .`, strict `pyright --pythonpath .venv/bin/python`, and
`git diff --check` passed. The complete suite in separate Postgres database
`altiscope_m3_issue50_test` passed **220 tests** with
`ALTISCOPE_DATABASE_URL=... .venv/bin/pytest -o addopts='' -q`.
`altiscope demo --stage pr_summary` and
`altiscope demo --stage aggregate --altitude manager` reproduced the M1/M2
credential-free examples. These checks exercise behavior; they do not evaluate
real model quality.

## Live preparation already saved

`examples/m3/collect_selected_prs.py` uses a GitHub CLI token without printing
it; `examples/m3/freeze_selected_sources.py` saves exact preparation and emits
only metadata. The checked-in
[source inventory](m3-workflow-sources-v1.json) records all 20 case IDs,
groups, PR numbers, snapshot IDs/versions, frozen source IDs/hashes, prepared
text hashes, and estimated token sizes. The total estimated prepared text is
58,780 tokens, with a 508–16,185 token range. No held-out source text is in the
inventory. A new run in another database must create and record new local IDs.

`examples/m3/prepare_openrouter_demo.py` saved these exact recipe versions in
the same database. It explicitly loads checked-in `config/models.yaml`, because
the local `.env` selects an Anthropic-only example registry. Preserve these
recipe IDs for the live run:

| Stage | Candidate: Sonnet | Baseline: Sonnet | Candidate: Gemini | Baseline: Gemini |
|---|---|---|---|---|
| PR | `3c846144-d947-422a-83eb-c2570eeb3df8` | `0a72212f-bc83-4677-b80c-ef504de2cae5` | `81841177-eb34-4ae7-b4c2-3ab8e2d8408c` | `e376a655-c879-4815-b769-aabc1a468398` |
| Aggregate | `b39518cd-7cd7-4045-8fcf-fa98cb9d0c46` | `58e3c9c6-5a69-43d5-84d2-16f3dfd10b29` | `b6b568f4-98fd-4a65-b9b0-c2e82c9f17d7` | `dfa7b9f7-4c4f-4a59-90f1-f27050c66616` |

The independent assessor is `cd012661-0d58-4d44-bb11-2d406ec26b04`.
Complete configuration and prompt hashes are stored in the database and printed
by the preparation script. No live invocation or aggregate source exists yet.
The original two preparatory PR sources for snapshot v1 are superseded for
this run by the 20-source inventory. Re-running preparation creates **new**
immutable recipe IDs; it does not resume these.

## Calls, estimate, and permission gate

The requested scope is eight upstream production PR reports for the aggregate;
80 PR comparison members; four aggregate comparison members; and 42
independent assessments of the two explicit candidates on each of 21 cases:
**134 initial calls**, plus at most one malformed-output repair per request.
No assessment of baselines is planned. A failed or skipped member is reported
explicitly. Aggregate input report IDs, hashes, rendered text, source ID, and
upstream costs must be recorded before the aggregate comparison runs.

As checked on 2026-09-17, OpenRouter lists Sonnet 5 at $2/M input and $10/M
output tokens, [Gemini 2.5 Flash](https://openrouter.ai/google/gemini-2.5-flash)
at $0.30/M and $2.50/M, and [GPT-5.5](https://openrouter.ai/openai/gpt-5.5/api)
at $5/M and $30/M. [Sonnet price](https://openrouter.ai/anthropic/claude-sonnet-5/api).
The 20 prepared PR texts estimate to 58,780 tokens in total before system
prompts and schemas. Applying the frozen per-request output reservations to
all 134 planned calls, and allowing a conservative 20,000 input tokens for
the aggregate plus source/output wrapping in assessments, gives an estimated
**about US$8 at maximum initial output** and **about US$16 if every request
needs its one allowed malformed-output repair**. The proposed cap is
**US$25**. These are configured-price planning estimates, not a provider bill;
actual usage, cache pricing, and errors may differ. Check recorded cost after
each PR and before each aggregate/upstream stage; stop before projected spend
exceeds the approved cap. The cap is **awaiting owner approval**.

`OPENROUTER_API_KEY` is configured locally in the ignored `.env` and is resolved
without logging or saving its value. The key was not used in this preparation.
**Do not start paid calls until the owner confirms the cap.**

## Next commands after access and cap are settled

Use the exact 20 saved source IDs in the inventory and recipe IDs above; do
not rerun preparation. Set `ALTISCOPE_DATABASE_URL` to the same local database
and `ALTISCOPE_MODELS_CONFIG=config/models.yaml` for upstream production reports.
Keep the OpenRouter key outside version control. The per-PR pattern is:

```bash
uv run altiscope comparisons run SOURCE_UUID_FROM_INVENTORY \
  --recipe 3c846144-d947-422a-83eb-c2570eeb3df8 \
  --recipe 81841177-eb34-4ae7-b4c2-3ab8e2d8408c
uv run altiscope summarize microsoft/markitdown HELD_OUT_PR_NUMBER
uv run python examples/m3/freeze_openrouter_aggregate.py EIGHT_REPORT_IDS_IN_DATASET_ORDER
uv run altiscope comparisons run AGGREGATE_SOURCE_UUID \
  --recipe b39518cd-7cd7-4045-8fcf-fa98cb9d0c46 \
  --recipe b6b568f4-98fd-4a65-b9b0-c2e82c9f17d7
uv run altiscope comparisons assess RESULT_UUID \
  --recipe cd012661-0d58-4d44-bb11-2d406ec26b04
```

Run the first command for every inventory row; generate eight upstream reports
in the held-out order in the dataset; use their exact IDs in the aggregate
freeze command. Run the final assessment command for each of the 42 explicit
candidate results. Do not inspect the real assessor verdict before any owner
workflow review that is intended to test the reveal sequence.
Record invocation, member, result, assessment, call, failure, usage, latency,
and cost IDs in a new immutable manifest before claiming live execution complete.
The final M3 walkthrough and release note must link saved outputs, owner workflow
review, full checks, CI, integration commit, and tag. Until then #50 and #6 stay open.
