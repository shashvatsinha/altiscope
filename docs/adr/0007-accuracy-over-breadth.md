# ADR-0007: Accuracy mechanisms

Status: proposed

## Context

The system's output is read by people with authority over other people. Errors are not
merely unhelpful; they misrepresent someone's work to someone who decides about them.
Outright factual error is only one failure mode. Selective emphasis (true claims that
leave out most of the work), overstatement, and evaluative framing are the others, and
they are harder to catch because every sentence is defensible in isolation.

## Decision

Mechanisms, in the order they act:

1. **Structure before prose.** Claims are atomic and typed; each carries evidence
   pointers that are validated against the snapshot. Narrative is composed from claims,
   not the other way round.
2. **Numbers from code, never from the model.** Computed facts are stored separately
   and rendered from data.
3. **Description vs. diff.** The atomic prompt is explicitly asked to report where the
   PR description and the diff disagree.
4. **Disclosure of what was not read.** The diff policy's exclusions are in the input
   manifest and are shown to the reader.
5. **Second-model verification** of every atomic claim, default on.
6. **Coverage reports** on every aggregate: which inputs were cited, which were not,
   with a threshold that marks low-coverage aggregates.
7. **Human flags** with categories that name the failure modes above, propagating from
   sources to the aggregates built on them, and feeding a regression set.
8. **No judgments about people.** Prompts describe work; they do not characterize
   people. Cross-developer views are side by side, not model-authored comparisons.

## Rejected

- Relying on a single high-quality model and a good prompt. Necessary, not sufficient;
  it provides no way for a team to check the system on their own PRs.
- Confidence scores from the model as the primary quality signal. Self-reported
  confidence is weakly calibrated; verification by a different model with the evidence in
  hand is a stronger and more auditable signal.

## Consequences

- Per-PR cost is roughly two model calls, once. This is the price of the property the
  system exists to provide.
- Prompts are versioned files with hashes; any change goes through the eval set.
