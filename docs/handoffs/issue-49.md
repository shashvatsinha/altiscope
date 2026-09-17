# Issue #49 checkpoint

Integration branch: `milestone/3-different-models-measurable-results`.
Implementation branch: `feat/49-comparison-inspection` (local commit: `git log -1`).
The implementation has not been pushed or integrated. Parent #6 and child #49 remain open.

## Implemented

- `show-comparison INVOCATION_UUID` reads saved PR or aggregate comparisons without
  generating or refreshing anything. It displays frozen identities, every member's
  output/failure, baseline labels, exact historical inputs and PR links, original
  generation and separate assessment accounting, invocation spend, and review measures.
- `--verbose` shows full frozen source, recipe configuration, prompt, and call attempts.
  `--review-session` only reveals assessment records whose exposure was persisted for
  that exact result/session. The default view hides verdicts and rationales.
- A follow-up inspection review confirmed historical recipes load without executable
  version checks, initial human rationale is visible in its selected session before
  assessment exposure, and post-assessment observations remain session-scoped.
  Zero-call cost is labeled `not incurred`.
- `examples/m3/offline_flow.py` and `docs/M3-RECIPES.md` give a credential-free
  create/run/inspect/review flow for #50. There is no new migration or prompt version.

## Validation

- `uv run ruff check .` and `uv run pyright`: passed.
- `uv run pytest -q` with local Postgres: passed, including new fixture-backed PR and
  aggregate inspection tests, existing comparison, assessment, and review suites.
- The offline example created and inspected a four-member comparison in local Postgres.
  It made no live model calls.

## Next action

Push the feature branch, open a PR targeting the M3 integration branch and linking
#49, run CI/review, then integrate under the repository workflow. Add this handoff and
the final PR/commit/check results to #49 or its linked PR. #50 can consume
`show-comparison`, `--review-session`, and the offline walkthrough after integration.
