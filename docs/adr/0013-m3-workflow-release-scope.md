# ADR-0013: Release M3 as a workflow demonstration

Status: Accepted by the owner in the issue #50 working session on 2026-09-17.

Issue: [#50](https://github.com/shashvatsinha/altiscope/issues/50), within
[#6](https://github.com/shashvatsinha/altiscope/issues/6).

## Context

The original [`m3-evaluation-v1`](../evaluation/m3-protocol-v1.md) requires
qualified technical and manager reviewers for 20 MarkItDown PRs and one held-out
aggregate. The owner has not worked on MarkItDown and cannot perform that source
qualification. No other qualified reviewers are arranged. Treating synthetic or
agent judgments as those reviews would misrepresent the evidence.

The owner instead wants to test the shipped comparison, assessment, inspection,
review, and export workflow, release M3, then demonstrate it to people who can
review their own repositories. Future prompt and model evaluation can use those
participants and a separately frozen study.

## Decision

M3 release evidence will be a bounded **workflow demonstration**, not a completed
human correctness or usefulness evaluation. The owner requested all 20 selected
public PRs and the specified `single_step` manager aggregate over the eight
2025-05-21 PRs. Run two OpenRouter
generation recipes and their prompt-only baselines, plus an independent OpenRouter
assessor on the explicit recipe results, subject to a recorded spending cap and
available credentials. The owner may review functionality and examples for release;
that review does not establish source-level correctness or model quality.

The 20-PR dataset and protocol v1 remain unchanged as historical study designs;
their confirmatory quality study is **not** being executed. Operational generation
and inspection will expose the eight originally held-out cases. They therefore
cannot later serve as untouched holdouts for prompt or model quality evaluation.
A later study must select a new held-out set, re-version its dataset/protocol,
qualify reviewers, freeze recipes and sources, and obtain real human judgments
before reporting quality or effort findings. Do not label the workflow
demonstration as a confirmatory run.

The architecture in ADR-0012 and the persistence contract remain in force:
provider neutrality, immutable source and result history, code-computed provenance,
versioned prompts, and append-only migrations. This decision changes the release
evidence claim, not those product contracts.

## Consequences

- M3 can show that the complete workflow executes on real saved sources, while
  correctness counts, reader usefulness, manual effort savings, and assessor
  detection rates remain **unmeasured**.
- The milestone title's “measurable results” means the system records outputs,
  failures, usage, cost, latency, and review history. It is not a validated
  accuracy result.
- The existing `m3-review-record-v1` interface is demonstrated with clearly
  labeled synthetic records. Owner inspection of real outputs is a release review,
  not a protocol-qualified correctness judgment.
- A qualified evaluation can be run as a separate, newly versioned study after
  M3 release, with fresh held-out cases.

## Evidence and follow-up

The issue #50 session contains the owner's explicit direction and the credential-free
pilot. [The workflow plan](../evaluation/m3-workflow-plan.md) records cases, calls,
budget, execution state, and next actions. Before release, update #6 and #50 with
this scope change and link the actual demonstration and review evidence.
