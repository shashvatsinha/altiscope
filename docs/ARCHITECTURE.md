# Architecture

Altiscope turns saved engineering activity into accounts readers can inspect. M1 connects
one public pull request to a CLI account. The broader product is described in the
[thesis](../THESIS.md), [roadmap](ROADMAP.md), and [decision records](adr/).

## 1. Implementation status

The M1 implementation is ready for review; release approval and live model validation
remain pending. See [release evidence](releases/m1.md) and the [walkthrough](M1-WALKTHROUGH.md).

| Area | Implemented in M1 |
|---|---|
| Collection | Public REST detail, paginated files/commits/reviews/both comment kinds, bounded retries, file and commit count reconciliation. |
| Storage | Postgres immutable source versions, raw payloads, relational evidence and one latest snapshot under concurrency. |
| Preparation | Computed facts, disclosed diff exclusions, deterministically ordered comments. |
| Generation | Provider-neutral structured output, complete-text request estimate, one malformed-output repair. |
| Publication | Overall v3 review linked to its PR; interpretation explicitly unverified. |
| Inspection | CLI account, excerpts, source version, prompt hash, model/provider identity and input omissions. |
| Demonstration | Credential-free synthetic fixture and optional persisted replay using the same services. |

Aggregate execution, semantic verification, private ingestion, authorization, feedback,
background sync and the web interface are future milestones.

## 2. From source to report

```text
Public PR → paginated collection → immutable Postgres snapshot
                                         ↓
                         computed facts + input manifest
                                         ↓
                      versioned prompt → registry → provider
                                         ↓
                       output shape checks → one repair
                                         ↓
                       calls + review + source PR association
                                         ↓
                          CLI account + sources + omissions
```

`ingest owner/repo NUMBER` saves a source. `summarize owner/repo NUMBER` operates only on
a stored merged PR. `show owner/repo NUMBER` reads the latest snapshot's selected account.
`demo` replays a recorded synthetic response; `demo --persist` also exercises storage.
The fixture provider is explicitly identified and never selected for live input.

## 3. Saving and preparing the source

The PAT client supports explicitly selected public repositories. Anonymous public reads
also work with lower rate limits. File/commit count mismatches and a changed PR timestamp
or head during collection reject the incomplete result. Missing patches are retained as
`None` and disclosed by the diff policy. GitHub does not provide a transactional snapshot
across endpoints: edits not reflected in its PR timestamp may escape this check.

The source writer serializes updates through the repository row. A partial unique index
enforces one latest source version. A hash of normalized material, excluding fetch time,
reuses unchanged source; changed material creates new source rows. Older files, comments,
commits and evidence remain intact. New source versions retain raw API payloads and fetch
time. Comment identity is `(kind, GitHub ID)`. Model input presents comments in deterministic
order with their kind, author, location and body.

Facts are computed in code. File policy excludes generated files, dependencies, missing
patches and oversized text. Stored input manifests disclose exclusions, counts and policy
settings. `show` uses stored facts and manifests so later policy changes cannot silently
change what an older account says it read.

## 4. Reviews and publication

[ADR-0010](adr/0010-pr-review-provenance.md) defines the v3 overall review. The
application attaches PR provenance; the model does not emit claim citations.
Code patches are primary input and PR prose is context. Every review is labeled
`interpretation unverified`. Humans can inspect its source PR; independent assessment
of the overall review is deferred. Per-claim assessment is not planned.

Malformed or empty output permits one replacement attempt. Refusal, truncation and
transport failure remain unpublished. Input omissions are disclosed. Publication
establishes usable output and PR traceability, not factual correctness.

## 5. Answering a reader's question

M1 describes one merged PR. Existing aggregate planning, reference checking and coverage
functions remain component foundations. M2 will add date-window resolution, execution,
altitude and original-PR lineage. M3 will add optional semantic verification and measured
model/prompt comparisons. No employee evaluation is supported.

## 6. Keeping results traceable

Postgres retains prompt versions, returned generation attempts, selected configuration,
request/response hashes and available usage/request metadata. Reviews publish atomically after checking that the input matches the stored PR snapshot. A new generation run retains earlier
runs. One current publication is selected per snapshot; a failed run does not displace it.
New source never silently reuses an old source's report.

Full retention duplicates the logical model request and response text. Hashes-only omits
those payloads while retaining metadata; source snapshots and published reviews remain.
Cost is an estimate using configured input/output rates, not an exact provider charge;
cache-specific pricing is not modeled. Process failure before persistence is not a durable
job retry mechanism. Background execution and crash recovery belong to later milestones.

Migrations are append-only. [0001](../migrations/0001_initial.sql) defines relational
provenance; [0002](../migrations/0002_snapshot_identity.sql) adds source hashing, latest
uniqueness, response/configuration provenance and retained generation reruns.
[0003](../migrations/0003_generation_provenance.sql) links every attempt to its source
and generation group, and retains the exact hashed prompt file.

## 7. Choosing AI models

Registry entries declare endpoints, models, capabilities, limits, prices and stage
preferences. New model support is configuration; new protocols require an adapter.
Orchestration imports no vendor SDK. The Anthropic adapter narrowly wraps SDK parsing to
retain raw metadata on parse failure; mocked HTTP tests cover this SDK dependency.

Routing follows preference and capacity. Complete system/user/schema text plus an envelope
allowance is estimated before each attempt; reserved output is subtracted by the registry.
Oversized material is rejected, never silently trimmed to fit. Estimates can be wrong;
provider refusal/truncation/failure is normalized and remains unpublished.

The [opt-in M1 configuration](../config/examples/m1.yaml) has documented provider capabilities.
A configured model is not an evaluated winner. No live generation result is claimed without
credentials and an actual run.

## 8. Running the service and handling feedback

M1 is a CLI with Postgres 15+. Docker Compose supplies Postgres 16. Setup, commands and
limits are in the [walkthrough](M1-WALKTHROUGH.md). Web service, worker, sign-in, access
control and feedback are not yet implemented.

## 9. Evaluation

Offline regressions cover PR review traceability, output withholding, repair limits, provider
outcomes, collection errors and storage invariants. The checked-in sample is synthetic,
with a hand-authored response and documented agent review. Owner review remains pending.
It does not establish live model accuracy. The human-reviewed 20-PR study belongs to M3.

## 10. Open questions

Owner review of proposed ADRs and the sample remains required before release. Later
milestones must resolve narrative reconciliation, aggregate lineage/coverage, semantic
review policy, private access and operational retention defaults. M1 does not settle
those decisions by implication.

Database cleanup of unused claim/evidence structures is deferred. Before extending
aggregation, verification, or feedback storage, follow the dependency checklist in
[ADR-0010](adr/0010-pr-review-provenance.md#deferred-database-cleanup).
