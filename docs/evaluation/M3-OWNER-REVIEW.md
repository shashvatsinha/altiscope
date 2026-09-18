# M3 owner review handoff

The JSON files are machine-readable audit records. They are not the thing to
read first. The saved comparison pages below are the human-facing view.

## What to review

This review is a workflow check. Please check that:

1. each comparison shows the frozen PR source and four outputs;
2. the Sonnet and Gemini candidate outputs are readable and easy to compare;
3. the prompt-only baselines are clearly labeled as controls;
4. model, latency, and cost are shown separately from the generated text; and
5. the assessment stays hidden until an initial judgment is recorded, then can
   be revealed and observed.

You are not being asked to decide whether the MarkItDown summaries are correct.
That requires a qualified reviewer familiar with the repository.

## Open a comparison

From the repository root, with the run database configured:

```bash
export ALTISCOPE_DATABASE_URL='postgresql://altiscope:altiscope@localhost:5432/altiscope_m3_issue50'
uv run altiscope show-comparison INVOCATION_ID
```

Use these invocation IDs for the eight PR cases:

| PR | Invocation |
|---:|---|
| 1259 | `be456267-c6a7-4307-9139-ca1d66bcc854` |
| 1256 | `6f9c12ec-89f1-4357-9394-0b3261ae973f` |
| 1241 | `a9d864a3-e3e7-42be-8e8c-b5d13865cdcf` |
| 1253 | `eacffec6-6fd4-4dec-814d-14c046de8352` |
| 1249 | `10bb1de3-3366-41df-a420-ae3e9b40e8f4` |
| 1245 | `a5f7500d-1295-4fce-8bfa-027a0af055ff` |
| 1201 | `8bbec7a5-610e-4d43-a3ee-7bd0d11ea5e5` |
| 1260 | `2382a0a4-c70e-4ba4-ade0-95c65bf0cc76` |

The manager aggregate is:

```text
1c16b063-25da-4601-b37c-b770ba2689a9
```

Add `--verbose` when you want the full generated text and source details.

## Guided review, if you want to test the review workflow

Start with a candidate result ID from `show-comparison`, for example the Sonnet
result for PR 1259:

```bash
uv run altiscope comparisons review \
  e46b4a39-4931-4204-8a46-506252e1fe1f \
  --reviewer owner-workflow-test \
  --case-id m3-heldout-pr-001 \
  --case-group held_out \
  --familiarity none \
  --familiarity-basis 'Workflow test; no MarkItDown repository experience' \
  --invocation-id be456267-c6a7-4307-9139-ca1d66bcc854
```

That command records the initial workflow judgment and returns a review-session
ID. Use that ID to inspect the session, reveal the saved assessment, record the
observation, and export the final record. The review can be about presentation
and usability; leave source-correctness fields as unavailable when you cannot
judge them.
