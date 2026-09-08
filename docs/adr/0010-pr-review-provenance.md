# ADR-0010: PR-level reviews and provenance

Status: accepted

Supersedes ADR-0009 and the mandatory claim citations and per-claim assessment
requirements in ADR-0007. The user approved this scope correction.

## Decision

M1 fetches a PR, produces a useful code-based review, and reliably traces that review
back to its PR. Humans inspect the review and its source. Provenance establishes
traceability, not factual correctness.

Schema/prompt v3 contains one overall review, without claim-level evidence fields.
The application links it to the immutable PR snapshot and model call. Code patches
precede PR prose in model input; prose supplies context rather than proof of changes.
Published output is explicitly unverified, and input omissions are disclosed.

Malformed or empty output permits one replacement attempt. Refusal, truncation and
transport failure remain unpublished. Citation matching and language heuristics do
not gate publication. The prompt continues to prohibit evaluating people.

No per-claim assessment is planned. An independent LLM may assess the overall review
in a later milestone. Human drill-down is to the source PR.

## Storage and compatibility

Store the review in the existing summary narrative column, linked to the source PR
snapshot and recorded model call. No new claim/evidence rows are needed. Historical prompt files remain as records. Development accounts from older schemas
are discarded; no old-format reader or migration of their content is needed.
A failed rerun does not displace a published review.

## Acceptance

Exercise collection, review generation, persistence and inspection. Verify the PR
association deterministically, preserve prompt/model/input provenance, and inspect
review usefulness against code changes. Passing shape checks does not prove accuracy.
