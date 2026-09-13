# M3 20-PR evaluation set, version 1

Dataset ID: `m3-markitdown-20-v1`

Protocol: [`m3-evaluation-v1`](m3-protocol-v1.md)

Status: selected on 2026-09-13; source snapshots and outputs are not yet frozen or run.

## Repository and selection rules

| Field | Selected value |
|---|---|
| Stable GitHub repository ID | `888092115` |
| Locator at selection | `microsoft/markitdown` |
| Visibility at selection | Public |
| Default/base branch | `main` |
| Repository URL | <https://github.com/microsoft/markitdown> |
| PR eligibility | Public, merged into `main`, complete GitHub snapshot collectable by Altiscope |
| Size metadata | GitHub additions + deletions and changed-file count, observed at selection |

The set is purposive, not random. The 12 development cases cover several converter
families, behavior boundaries, a security boundary, an external-service integration,
and change sizes that remain practical for source review. They may be used to improve
prompts and fixtures. The eight held-out cases are the complete census of PRs GitHub
reports as merged on 2025-05-21 UTC. They were selected from identity and PR metadata
(number, title, merge time, base, and change-size counts); their source content and future
outputs are reserved for the final evaluation.

Selection reasons describe change and study coverage only. They do not characterize an
author, reviewer, team, or employee. This small set does not represent all MarkItDown
work or support a general accuracy claim.

## Development PR cases

Lines are `additions + deletions`; they are selection metadata, not a productivity metric.

| Case ID | PR | Merged (UTC) | Lines / files | Selection reason |
|---|---:|---|---:|---|
| `m3-dev-pr-001` | [#19](https://github.com/microsoft/markitdown/pull/19) | 2024-12-16 21:49:48 | 23 / 4 | Text-decoding boundary with a compact implementation and tests. |
| `m3-dev-pr-002` | [#22](https://github.com/microsoft/markitdown/pull/22) | 2024-12-16 21:56:25 | 129 / 4 | New archive converter and nested-input behavior. |
| `m3-dev-pr-003` | [#33](https://github.com/microsoft/markitdown/pull/33) | 2024-12-16 22:11:50 | 29 / 3 | Presentation-chart behavior in a small multi-file change. |
| `m3-dev-pr-004` | [#48](https://github.com/microsoft/markitdown/pull/48) | 2024-12-17 00:19:10 | 11 / 2 | Keyword-forwarding bug with a narrow behavioral boundary. |
| `m3-dev-pr-005` | [#71](https://github.com/microsoft/markitdown/pull/71) | 2024-12-17 23:41:51 | 151 / 2 | Notebook converter addition with generated-file omission relevance. |
| `m3-dev-pr-006` | [#97](https://github.com/microsoft/markitdown/pull/97) | 2024-12-17 23:34:23 | 153 / 3 | Feed converter addition for another source family. |
| `m3-dev-pr-007` | [#129](https://github.com/microsoft/markitdown/pull/129) | 2024-12-18 20:11:01 | 37 / 2 | Path-traversal security boundary; tests whether wording stays source-bounded. |
| `m3-dev-pr-008` | [#169](https://github.com/microsoft/markitdown/pull/169) | 2025-01-03 21:58:17 | 40 / 4 | Spreadsheet-format support across implementation and registration. |
| `m3-dev-pr-009` | [#196](https://github.com/microsoft/markitdown/pull/196) | 2025-01-03 21:34:39 | 89 / 4 | Outlook message converter and format-specific behavior. |
| `m3-dev-pr-010` | [#303](https://github.com/microsoft/markitdown/pull/303) | 2025-01-24 22:09:32 | 123 / 3 | External document-intelligence integration and configuration. |
| `m3-dev-pr-011` | [#1153](https://github.com/microsoft/markitdown/pull/1153) | 2025-03-25 04:43:04 | 273 / 4 | Larger URI API change spanning behavior and interface naming. |
| `m3-dev-pr-012` | [#1160](https://github.com/microsoft/markitdown/pull/1160) | 2025-03-28 22:36:39 | 1,083 / 11 | Largest selected case; complex DOCX math behavior tests practical review limits. |

## Held-out PR cases

These eight rows are all PRs returned by the selection query
`repo:microsoft/markitdown is:pr is:merged merged:2025-05-21`. Do not inspect their
prepared source or generated outputs for tuning before the final freeze.

| Case ID | PR | Merged (UTC) | Lines / files | Selection reason |
|---|---:|---|---:|---|
| `m3-holdout-pr-001` | [#1259](https://github.com/microsoft/markitdown/pull/1259) | 2025-05-21 16:47:14 | 19 / 3 | Exhaustive window member; parser/security dependency boundary. |
| `m3-holdout-pr-002` | [#1256](https://github.com/microsoft/markitdown/pull/1256) | 2025-05-21 17:02:17 | 94 / 26 | Exhaustive window member; broad maintenance-only contrast case. |
| `m3-holdout-pr-003` | [#1241](https://github.com/microsoft/markitdown/pull/1241) | 2025-05-21 17:17:57 | 20 / 1 | Exhaustive window member; compact YouTube error handling. |
| `m3-holdout-pr-004` | [#1253](https://github.com/microsoft/markitdown/pull/1253) | 2025-05-21 17:22:08 | 4 / 1 | Exhaustive window member; very small configuration behavior. |
| `m3-holdout-pr-005` | [#1249](https://github.com/microsoft/markitdown/pull/1249) | 2025-05-21 17:47:29 | 26 / 2 | Exhaustive window member; runtime requirement and repository config. |
| `m3-holdout-pr-006` | [#1245](https://github.com/microsoft/markitdown/pull/1245) | 2025-05-21 21:34:51 | 40 / 3 | Exhaustive window member; MCP transport capability. |
| `m3-holdout-pr-007` | [#1201](https://github.com/microsoft/markitdown/pull/1201) | 2025-05-21 22:12:22 | 2 / 1 | Exhaustive window member; trivial documentation restraint case. |
| `m3-holdout-pr-008` | [#1260](https://github.com/microsoft/markitdown/pull/1260) | 2025-05-21 22:24:57 | 4 / 2 | Exhaustive window member; release-metadata restraint case. |

The held-out order above is the deterministic aggregate input order: `merged_at`
ascending, then PR number ascending. Review presentation order is independently shuffled
and recorded by #50.

## Held-out aggregate case

| Field | Value |
|---|---|
| Case ID | `m3-heldout-manager-day-2025-05-21` |
| Group/kind | `held_out` / `aggregate` |
| Repository identity | GitHub ID `888092115`; locator at selection `microsoft/markitdown` |
| Window | `2025-05-21T00:00:00Z` through `2025-05-21T23:59:59.999999Z`, inclusive |
| Altitude | `manager` |
| Query instruction | `Repository: microsoft/markitdown\nMerged from 2025-05-21T00:00:00+00:00 through 2025-05-21T23:59:59.999999+00:00 (inclusive).\nReader altitude: manager` |
| Selection rule | Every merged PR in the repository whose `merged_at` is within the inclusive UTC window, ordered by `merged_at`, then PR number |
| Experiment scope | ADR-0012 `single_step` composition over identical exact saved input reports |
| Selected inputs | The eight held-out PR cases above, in listed order |
| Additional window inputs | None at selection; GitHub search returned exactly eight on 2026-09-13 |
| Exact report versions/hashes | Pending #50; all eight must be successful and frozen before aggregate source creation |

The aggregate is conditional on the same eight saved PR-report documents. It does not
compare end-to-end PR summarization or tree planning. No development PR or report may be
an aggregate input. No development aggregate is selected in version 1, so no aggregate
can mix development and held-out material. If collection later finds a window member
absent from this table, do not omit it: stop, record the discrepancy, and revise/version
the dataset before held-out exposure. If a listed input report is missing or failed, the
aggregate remains blocked.

## Collection and freeze checklist for #50

1. Resolve the current locator and verify it still maps to repository ID `888092115`.
2. Ingest each PR and verify merged state, `main` base, complete file collection, and the
   PR number under that repository ID. A locator rename is metadata, not a new repository.
3. Freeze every exact snapshot and prepared source, recording the IDs, versions, content
   hashes, facts, exclusions, policy, renderer, source-format, and framework versions.
4. Do not display held-out prepared content or outputs until all recipes, assessment
   contract, protocol, reviewer assignments, and presentation plan are frozen.
5. Produce/select one exact successful PR report for each aggregate input without tuning
   on held-out content. Freeze its report ID/version, output and rendered-text hashes,
   source hash, and ordinal. All recipes then receive that identical ordered input set.
6. Fill and hash the final manifest required by the protocol. Record generation and
   assessment IDs after execution without changing its frozen specification.

## Revision log

| Date | Version | Change |
|---|---|---|
| 2026-09-13 | `m3-markitdown-20-v1` | Initial MarkItDown selection for issue #47. |
