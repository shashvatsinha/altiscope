# ADR-0007: Check accuracy and expose omissions

Status: proposed

## Context

Reports can misrepresent work through factual errors, overstatement, or selective
emphasis. A report may contain true statements while omitting relevant work. Readers
need ways to inspect evidence, see omissions, and report errors.

## Decision

1. **Claims with evidence.** Represent each statement as a claim with references checked
   against the source snapshot. Compose narrative from those claims.
2. **Computed facts.** Calculate numbers in code, store them separately, and render
   them from data.
3. **Source disagreements.** Ask the model to identify differences between the pull
   request description and its diff.
4. **Excluded material.** Record files excluded by the diff policy in the input
   manifest and show that list to readers.
5. **Second-model review.** Review every claim about an individual pull request, with
   review enabled by default.
6. **Coverage.** Report cited and uncited inputs for each aggregate and mark results
   below a configured threshold.
7. **Human feedback.** Categorize reported errors, show flags on summaries that use
   disputed sources, and use corrections as regression cases.
8. **Describe work.** Exclude judgments about people. Any cross-developer view would
   show separate accounts side by side, without AI-written comparisons.

## Alternatives considered

- **Rely on one model and its prompt.** This lacks a separate review of whether evidence
  supports the output. Evaluation on the team's own examples is still needed.
- **Use model confidence as the primary quality signal.** A confidence score does not
  explain whether the evidence supports a claim. A second model can provide an
  inspectable explanation, though its usefulness must also be tested.

## Consequences and gaps

- Review adds model calls, cost, and latency. Its benefit needs measurement; separate
  models can share errors.
- Prompts are versioned and hashed. The proposed evaluation process should check changes
  before adoption; the evaluation set and runner remain unbuilt.
- The current schema generates narrative and claims together. Validation does not
  reconcile every sentence with the claims, so the first decision above is not yet
  enforced. Publication rules remain an
  [open question](../ARCHITECTURE.md#10-open-questions).
- Computing facts does not prevent generated prose from misstating them. Coverage counts
  immediate inputs cited, which may be child summaries; it does not measure completeness
  of the original work. Reader feedback and the review workflow remain unbuilt.
