# M3 evaluation protocol, version 1

Protocol ID: `m3-evaluation-v1`

Dataset: [`m3-markitdown-20-v1`](m3-eval-set-v1.md)

Record contract: `m3-review-record-v1`, illustrated by
[`m3-review-record-v1.example.json`](m3-review-record-v1.example.json)

Status: selected and executable, but not frozen or run. Issue #50 owns the final
recipe/source freeze, live generation, human judgments, analysis, and reporting.

## Purpose and claim boundary

This protocol compares frozen generation recipes on identical saved sources. It asks:

1. Is each generated account correct as a whole against its saved source?
2. Is it useful for its specified reader and task?
3. How much active human effort is required to prepare, read, check, and correct it?
4. When an independent assessment is available, does revealing it find a real
   problem, create a false alarm, miss a problem, or change usefulness and effort?

The study is a practical evaluation of 20 selected public PRs and one aggregate case.
It is not a statistically representative estimate for MarkItDown, other repositories,
or model families. It does not evaluate contributors or employees. Reviewer and author
identity must never be used as an explanatory variable or reported as a score.

Human-written comparison accounts are **not included in M3 v1**. Consequently, M3 may
compare recipes, correctness, usefulness, generation performance, and the effort to
review generated accounts. It must not claim time saved versus manually preparing an
account. A later study that adds manual accounts needs a new protocol version and must
measure their preparation under the same source and reader task.

## Experimental units and conditions

The dataset contains 20 atomic PR cases: 12 development and 8 held-out. It also contains
one held-out aggregate case built from the eight held-out PRs. The aggregate experiment
is the ADR-0012 `single_step` scope: every recipe receives the same ordered, exact saved
PR-report versions, query, altitude, and rendered input. It does not measure source-report
generation, tree planning, end-to-end tree quality, or the earlier cost of its inputs.

Issue #50 freezes exactly three generation conditions for the confirmatory set: two
Altiscope comparison recipes and the simpler baseline from #46. Each is requested once
for each case: 60 PR members and 3 aggregate members, or 63 requested members total.
Adding another condition requires a recorded protocol revision because it changes both
review burden and multiplicity. A forced rerun or a cache reuse does not create another
PR or aggregate observation. If two reviewers inspect the same result, their judgments
are repeated measurements of one result, not independent source cases.

The primary analysis unit is a selected case. Results are nested under their case and
recipe. The aggregate remains one aggregate case; it must never be pooled as a twenty-
first PR. Reused results keep their original result and review identity.

Development cases may be used for fixtures, pilots, prompt changes, and workflow tuning.
Held-out identities and eligibility metadata may be collected, but their snapshot
content, prepared text, generated outputs, assessments, and human findings must not
guide recipe, prompt, rubric, or workflow tuning before the final freeze. Automation
may collect and hash held-out sources without displaying them to the tuning team.

## Reviewer arrangement and familiarity

Use study identifiers such as `reviewer-t1`; no account or authentication system is
required. Record the reviewer role and familiarity for every review session. Familiarity
describes evidence relevant to checking the work, not the quality of a person.

The minimum feasible arrangement is:

- A primary technical reviewer checks every successful PR result as reader role `ic`.
  For each case this reviewer must be qualified by direct/repository familiarity, or by
  both domain familiarity and the recorded preparation step.
- A manager reader familiar with the repository's purpose or document-conversion work
  reviews every successful aggregate result as role `manager`.
- A technical adjudicator reviews every `incorrect` or `unclear` judgment, every error
  discovered only after assessment reveal, and every reviewer disagreement. The
  adjudicator may be the manager reader only when they meet the technical qualification.

If no reviewer satisfies these gates, #50 may demonstrate the workflow but may not call
the records a completed human correctness evaluation. It must recruit a qualified
reviewer or revise and re-version the dataset before held-out exposure.

Record one familiarity level plus a short basis:

| Value | Meaning |
|---|---|
| `direct` | Authored, reviewed, or maintained the affected behavior. |
| `repository` | Contributed to or maintained the repository/subsystem, but not this change. |
| `domain` | Has implemented or reviewed similar document-conversion or Python behavior. |
| `prepared` | Learned this case only through the protocol's source-preparation step. |
| `none` | No relevant familiarity; not qualified for the primary correctness judgment. |

Multiple applicable facts belong in `familiarity_basis`; store the strongest level.
A `domain` reviewer is qualified only after preparation. A `prepared`-only reviewer can
record usefulness but cannot be the sole correctness reviewer.

## Review sequence

Use a guided session for each reviewer and case. Recipe/model names remain concealed
until the case's initial judgments are complete where the interface permits it. The final
manifest records the shuffle algorithm, seed, concealed labels, source order, and actual
presentation order; the review record stores the ordinal actually seen.

1. **Declare exposure.** Before showing a result, record whether the reviewer has already
   seen any target assessment: `none_declared`, `known`, or `unknown`. If known, append
   the corresponding prior/external exposure event. Absence of an event is not by itself
   proof of blindness.
2. **Prepare once per case.** With assessments hidden, inspect the frozen source,
   omissions manifest, reader task, and any relevant saved tests or discussion. Stop the
   preparation timer before any candidate result is shown. Reuse this preparation record
   across recipe results for the same reviewer and case.
3. **Read one result.** Start a result-specific reading timer, show the concealed result,
   and stop when the reviewer can explain it. Do not inspect the assessment.
4. **Check it.** Compare the complete result with the exact frozen source and omissions.
   Stop before writing a correction. Record the whole-result correctness label, rationale,
   pre-assessment usefulness score, and any correction as the immutable initial revision.
5. **Commit before reveal.** Persist the initial revision and its exposure state before
   offering any assessment. The workflow must reject a guided reveal without that commit.
6. **Reveal when assigned.** For every successful result with a successful independent
   assessment, append an exposure event with the exact assessment ID, event ordinal,
   timestamp, kind, and presentation position. Time only the additional work caused by
   reading and checking the assessment.
7. **Observe and revise.** Record result-level true detection, false alarm, missed problem,
   and inconclusive status; post-assessment usefulness; and a linked append-only revision
   when judgment, rationale, or correction changes. Never overwrite the initial revision.

The initial revision is `confirmed_unexposed` only when `none_declared` was recorded and
no exposure event preceded it. Otherwise its blind status is `known_exposed` or `unknown`.
Only `confirmed_unexposed` revisions enter the primary pre-assessment analysis.

## Whole-result correctness rubric

Correctness is a judgment about the account as a whole, not a stored table of claims.
Use the saved source and recorded omissions; do not assume omitted material supports a
statement. Record one label:

| Label | Rule |
|---|---|
| `correct` | No material statement is contradicted or unsupported, and no material omission makes the account's overall meaning misleading for the assigned reader. Minor style problems or intentionally omitted low-value detail do not fail it. |
| `incorrect` | At least one material contradiction, unsupported assertion, scope error, or omission would leave the assigned reader with a wrong understanding of the change. Record a result-level rationale and, when feasible, corrected account text. |
| `unclear` | The frozen evidence is insufficient or genuinely ambiguous after the qualified reviewer and adjudicator make a reasonable check. Explain what prevents resolution. This is not a substitute for an unfinished review. |

A generation failure has no correctness label. An assessment failure is not a human
disagreement. Automated schema validation is not evidence of factual correctness.

## Reader usefulness rubric

The task for `ic` readers is: *understand what behavior changed, its important technical
boundary, and where further source inspection is needed*. The task for `manager` readers
is: *understand the important work in the period, its scope, and what should be followed
up, without needing implementation trivia*. `exec` is reserved for a later case.

Record usefulness before assessment reveal and again after reveal when an assessment is
shown. Use this five-point ordinal scale; zero is not a score:

| Score | Anchor |
|---:|---|
| 1 | Harmful or unusable for the task; it would materially mislead the reader. |
| 2 | Little usable value; major reconstruction or missing context is required. |
| 3 | Some usable value, but substantial checking, editing, or context is required. |
| 4 | Useful with minor checking, editing, or contextual qualification. |
| 5 | Directly useful for the task as written, while preserving appropriate uncertainty. |

Usefulness and correctness are separate. A correct but trivial account can score low;
a fluent account with a material error is `incorrect` even if it initially seems useful.
Every score includes a short rationale tied to the assigned task and role.

## Effort measures and non-overlap rules

All durations use integer **milliseconds** of active wall-clock time from a monotonic
timer. Pause for interruptions. Manual estimates are allowed only when the timer fails
and must use `method=estimated`. Each measure has `status=measured`, `not_applicable`, or
`unavailable`; only `measured` has a nonnegative value. Missing is never encoded as zero.

| Component | Cardinality | Start/stop rule |
|---|---|---|
| `preparation` | Once per reviewer + case + frozen source | Read source, omissions, task, and shared context before any candidate output. Stop before the first result appears. |
| `reading` | Once per reviewer + exact result | Read only the generated account until understood. Exclude source checks and assessment. |
| `checking` | Once per reviewer + exact result, pre-reveal | Verify the account against frozen evidence. Stop before writing corrections. |
| `correction` | Per revision when correction is performed | Draft or revise corrected account text. Use `not_applicable` when no correction task is performed. |
| `assessment_related` | Per revealed assessment | Read the assessment, investigate only the questions it raises, and decide whether to revise. Exclude correction-writing time. |

A measured zero is retained as zero; it means the timer measured no elapsed milliseconds,
not that the value was missing. An unavailable measurement requires a reason such as
`timer_failure`, `interrupted`, or `not_collected`. Preparation is shared: primary
per-result effort is `reading + checking + correction + assessment_related`, while
case-total effort adds preparation exactly once. Never add the same preparation duration
to every recipe. An evenly allocated preparation sensitivity analysis is allowed only if
it is labeled and the unallocated totals remain primary.

Generation latency and model cost are system measures, not human effort. Earlier PR-report
generation for an aggregate is outside the measured single composition step.

## Assessment reveal and adjudication

An assessment exposure records one of `guided_reveal`, `declared_prior_external`,
`accidental`, or `general_inspection`. It points to the exact assessment and result.
Assessment status remains separate: `not_run`, persisted `failed`, valid `inconclusive`,
or a successful `agree`/`disagree` verdict under #45's contract.

After a reveal, record these nullable result-level observations. They are not per-claim
assessment annotations, and more than one boolean may be true:

- `true_problem_detection`: the assessment caused or confirmed discovery of a material
  problem that the human adjudication accepts.
- `false_alarm`: the assessment alleged a material problem that adjudication rejects.
- `missed_problem`: the human found a material problem that the assessment did not flag.
- `inconclusive`: available evidence cannot resolve whether the assessment observation
  is a true detection, false alarm, or miss.

When no problem exists and assessment and human agree, all four are false and the text
observation records `no_problem_agreement`. When assessment was not run or failed, these
fields are unavailable, not false. A valid assessment verdict of `inconclusive` normally
sets the observation `inconclusive=true`, unless later evidence permits adjudication.

If an error is discovered only after reveal, retain the initial label and rationale.
Append a new revision linked to the exposure, record the later label, correction and
reason, and set `true_problem_detection` when the assessment led to the confirmed error.
The final adjudicated label supports a secondary analysis; it never replaces the primary
blind record.

## Failures, missingness, and denominators

Every table and percentage reports its numerator and denominator plus counts for excluded
states. The rules are:

- **Generation reliability:** denominator is every requested recipe-case member in the
  frozen manifest. Report `succeeded`, each persisted failure status, `pending`, and
  interrupted/unrecorded outcomes. A failure contributes no correctness or usefulness
  score. Reuse contributes zero new calls/cost and does not create a new output.
- **Correctness distribution:** denominator is unique successful results assigned for
  review. Report counts for `correct`, `incorrect`, `unclear`, and missing judgment. The
  binary correct fraction, if shown, uses only `correct + incorrect` and is labeled
  “among determinate judgments”; `unclear` and missing remain visible.
- **Usefulness:** denominator is unique successful result-reviewer records with a measured
  score for the specified role and time point. Unavailable and uncollected scores are
  reported separately, never as zero. Before/after change requires the same reviewer,
  result, role, and a recorded exposure between measurements.
- **Human effort:** calculate summaries only from `measured` durations and show counts of
  `not_applicable` and `unavailable` by component. Case totals include shared preparation
  once. Do not infer zero cost or time from missing provider or timer data.
- **Assessment observations:** the assessment-availability table includes `not_run`,
  `failed`, `inconclusive`, and successful statuses. Detection/false-alarm/miss summaries
  use only successful assessments with completed human adjudication; all exclusions are
  counted. An assessment failure is never agreement or disagreement.
- **Review revisions:** primary correctness and usefulness use the committed pre-reveal
  revision. Post-reveal and final-adjudicated values are separately named secondary
  analyses. Known/unknown prior exposure is excluded from primary blind comparisons and
  shown as its own count.

Break down all outcomes by exact recipe version, case ID, case kind (`pr` or `aggregate`),
and group (`development` or `held_out`). Show the aggregate case separately. Aggregate PR
case summaries first within each of the 20 PRs before any descriptive across-case summary;
do not pool multiple outputs or reviewers as independent PRs. Development and held-out
results are never combined into a single headline number.

Report counts, medians, ranges, and individual case results. With this purposive sample,
do not attach population confidence intervals or make a general model-accuracy claim.

## Final freeze manifest

Issue #50 creates one immutable final manifest before any held-out output is displayed.
The manifest and every retained protocol/dataset document are stored with content and
SHA-256, not only a filename. Freeze fails if any required field is unknown.

The manifest contains:

- manifest ID/version, freeze timestamp, operator, and a revision note;
- protocol ID/version/content/hash and dataset ID/version/content/hash;
- framework package version and exact Git commit;
- for every PR case: repository numeric ID, locator at selection, PR number, frozen
  snapshot ID/version/source hash, prepared-source hash, facts/input-policy/renderer and
  source-format versions, and group;
- for the aggregate: `single_step`, repository identity, exact inclusive UTC bounds,
  selection rule, `manager` altitude, exact query instruction, comparison-source hash,
  renderer/source-format versions, and the ordered exact successful input-report IDs,
  versions, output hashes, rendered-text hashes, and source hashes;
- every comparison and baseline recipe version ID/name/version/configuration hash, prompt
  version/hash, output schema version/hash, frozen model/provider/settings/pricing and
  implementation versions required by ADR-0012;
- the assessor recipe/schema/rubric/prompt versions, underlying-model independence
  evidence and policy version, or an explicit `not_run` plan;
- presentation shuffle algorithm/version/seed and concealed-label mapping;
- expected invocation members and, filled after execution, exact invocation/member/result
  IDs, dispositions, terminal statuses, assessment IDs/statuses, and any interruption;
- reviewer study IDs, assigned roles, qualification status, and adjudication assignment.

For `m3-heldout-manager-day-2025-05-21`, all eight exact input reports are pending until
#50 generates or selects and freezes them. Missing or failed input reports block aggregate
source creation; none may be silently omitted or replaced by a newer version.

Revisions before freeze are allowed but must update the protocol or dataset version and
revision log when material. After held-out exposure, tuning preserves the original
manifest and evaluation. A changed run is labeled exploratory, or uses a newly selected
holdout and new protocol/dataset version. Final held-out findings never retroactively
become development evidence.

## Persistence handoff for #42 and #48

The JSON example is the normative field-level payload for `m3-review-record-v1`; this
section defines relational ownership and cardinality. Equivalent normalized tables are
preferred over storing only opaque JSON, but the complete versioned payload must remain
exportable and reloadable.

| Logical record | Required identity/content |
|---|---|
| Review session | Session ID, exact result ID, reviewer ID, protocol and dataset IDs/versions/hashes with retained content, case/group/kind, reader role, familiarity level/basis, declared prior exposure, actual result presentation ordinal, timestamps. |
| Preparation | Shareable preparation-record ID, reviewer + case + frozen-source identity, one effort measurement. The same record may be referenced by several result reviews and counted once. |
| Revision | Immutable ID and ordinal, previous revision ID, kind, correctness/rationale/correction, usefulness/status/rationale, correction effort, blind status, IDs of all exposure events seen, timestamp. Ordinals and parent links are contiguous within a session. |
| Exposure | Immutable ID and ordinal, session/reviewer/result, exact assessment ID when known, exposure kind, actual assessment presentation ordinal, timestamp. The assessment must target the same result. |
| Post-assessment observation | Exposure ID, assessment status/verdict, nullable true-detection/false-alarm/missed/inconclusive fields, rationale, assessment-related effort, post-usefulness, and resulting revision ID if any. |
| Effort measurement | Component, unit `milliseconds`, status, nullable value, method, and unavailable reason. Constraints enforce value iff status is `measured`. |

Storage must preserve exact-result association across cache reuse and forced reruns. It
must reject mismatched result/assessment/exposure references, stale revision parents,
duplicate ordinals, and a guided reveal without a persisted initial revision. Corrections
are evaluation artifacts and never update the immutable generated result.

## Revision log

| Date | Version | Change |
|---|---|---|
| 2026-09-13 | `m3-evaluation-v1` | Initial protocol and downstream persistence contract for issue #47. |
