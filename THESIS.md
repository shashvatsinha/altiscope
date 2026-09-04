# Thesis

This document argues for why Altiscope should exist and why the problem it addresses may
be tractable now in a way it was not five years ago. It is an argument, not a
specification. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) describes the proposed
implementation; [`docs/adr/`](docs/adr/) records individual engineering decisions.

Nothing here has been validated. The final section states the argument as a set of
hypotheses, which is the form in which it should be read.

## 1. The problem is understanding, not data

An engineering organization of any size produces a continuous, detailed, machine-readable
record of its own work. Pull requests carry descriptions, diffs, review discussions and
commit histories. Issue trackers carry intent. Incident reports carry consequences. The
record is unusually good compared with most other kinds of organizational work: it is
written down, timestamped, attributable, and available through APIs.

What the organization lacks is not the record. It is an account of what the record means
at the level of abstraction each reader needs. An engineer knows what their pull requests
did. Their lead knows roughly what the team did. A director two levels above knows what
someone told them, filtered through two rounds of summarization performed by people with
their own priorities, incomplete visibility and limited time. By the time a description
of engineering work reaches a decision-maker, it has usually been rewritten several
times, and the connection back to the underlying evidence has been severed. Nobody can
check it, because there is nothing left to check against.

This is a compression problem. Specifically, it is a *semantic* compression problem: the
transformation of local technical evidence into statements that are true, at a coarser
grain, about a larger scope. It is distinct from the storage or retrieval problems that
most engineering data tools solve well.

## 2. Hierarchy as an information-routing mechanism

In March 2026, Jack Dorsey and Roelof Botha published
[*From Hierarchy to Intelligence*](https://block.xyz/inside/from-hierarchy-to-intelligence),
which traces organizational hierarchy from the Roman army through the Prussian General
Staff, the American railroads, and the postwar matrix corporation. Their central
historical observation is that hierarchy is, among other things, an information-routing
protocol shaped by a human constraint: a person can effectively coordinate a small number
of others, so scale is bought by adding layers, and each layer costs latency and
fidelity. They argue that this trade-off has been the governing constraint on
organizational design for two thousand years, and that the reason repeated attempts to
flatten organizations have reverted to hierarchy is that no alternative mechanism was
capable of performing the routing.

Block's own response is ambitious: a continuously maintained "company world model" built
from the machine-readable artifacts of remote-first work, a customer world model built
from transaction data, an intelligence layer that composes capabilities from both, and an
organization normalized to three roles with no permanent middle-management layer. That
is a claim about a whole company, asserted from inside a transition its authors say is
early and expected to break in places.

Altiscope takes one narrow implication of the historical observation and nothing else.
If part of what management layers do is compress and route information about work, then
it is worth asking whether a well-defined slice of that compression — describing
engineering activity evidenced in pull requests, at a chosen level of abstraction, over a
chosen scope — can be performed by a system in a way that a reader can inspect and
correct. That is a smaller question, and unlike the larger one it can be tested on a real
repository within a quarter.

Three things Altiscope does not claim, worth stating here rather than at the end. It does
not implement the Dorsey–Botha thesis; it addresses one function of one layer for one kind
of work. It does not propose that management hierarchy becomes unnecessary; describing
work is a small part of what managers do, and the parts Altiscope does not touch —
judgment, development, advocacy, decisions about people — are the parts that matter most.
And it is not an organizational world model; it has no representation of strategy,
priority, customers, or anything outside the pull requests it has read.

## 3. Why measurement has not closed the gap

Engineering analytics tools measure quantities: pull request counts, cycle time, review
latency, deployment frequency, change failure rate. These measures are useful. They
detect trends a narrative would miss, they are cheap to compute, they are hard to argue
with, and the better ones (DORA metrics, for instance) correlate with outcomes people
care about.

They also answer a different question. "The platform team merged 84 pull requests last
quarter, median cycle time 31 hours" and "the platform team replaced the synchronous
billing webhook path with a queue-backed one, which is why the November incident class
stopped recurring" are not competing answers of differing quality. They are answers to
different questions. The first is a measurement; the second is an interpretation of
content. A dashboard cannot produce the second because the information required is in the
diffs and the discussion, not in the counts.

The category difference matters because organizations often substitute one for the other
under pressure. When a director needs to know what a team accomplished and the only
machine-produced input available is a throughput chart, the chart gets used as if it
answered the question. Adding more measures does not fix this; it produces more precise
answers to the question that was not asked.

## 4. What changed

Semantic interpretation of technical material used to require a person who could read
code. That made the cost of interpretation scale with the volume of work, which is why
organizations pushed the task down to the people closest to it and accepted the losses
introduced by each subsequent retelling.

Contemporary language models change the economics of that step. A model can now read a
complete pull request — description, full diff, review threads, commit messages — and
produce a description of what changed that is frequently accurate and occasionally
better than what a busy engineer would write about their own work a month later. Long
context windows mean a bounded artifact like a pull request can be read whole rather than
sampled. Structured output means the result can be a typed object rather than prose.
These are recent enough capabilities that a design predicated on them would have been
unreasonable in 2022.

This is a genuine change in feasibility. It is not, by itself, a solution.

## 5. Why summarization alone is not sufficient

A model that reads pull requests and emits prose creates a new problem in place of the
old one. The old problem was that human summarization loses information and cannot be
audited. The new problem is that model summarization loses information, cannot be
audited, and is produced fluently enough to obscure the fact.

The failure modes are specific and they compound with organizational distance:

- The model states something the diff does not support. A reader without the diff cannot
  tell.
- The model states something the diff does support but misreads its significance —
  describing a lock as making a function thread-safe, when the shared state it protects
  is mutated elsewhere.
- The model produces a summary in which every sentence is defensible and which
  nevertheless misrepresents the period, because most of the work in scope went
  unmentioned. Section 6 returns to this one; it is the hardest of the four to detect.
- The model adopts an evaluative register about the people involved, which a reader with
  authority over those people then treats as an assessment.

None of these are addressed by a better prompt, a larger model, or a self-reported
confidence score. Each of them is a property of the *system* around the model, and each
of them requires a different mechanism. The distinction that organizes Altiscope's design
is between:

    documents → model → prose

and

    stored evidence → deterministic facts → structured claims + evidence pointers
      → validation → verification → aggregation → coverage → narrative

In the second chain the model's output is an intermediate representation subject to
checking, not the artifact the reader consumes. Prose is generated last, from claims that
have already survived validation, and every sentence in it remains connected to the rows
that justify it. Interpretation is what the model contributes; numbers, identifiers and
authority come from elsewhere.

## 6. Distinctions the design depends on

Four distinctions do most of the work in the argument. They are easy to collapse and the
design is not coherent if they are.

### Provenance versus accuracy

Provenance records what a claim rests on. A claim can cite a real file, a real hunk, and a
real review comment, and still be wrong about what that code does. Provenance does not
establish correctness; it establishes *inspectability*. It makes the evidential basis of
a statement available, which is the precondition for anything else — a reviewer, a second
model, a person who wrote the code — to evaluate it. Systems that treat citation as proof
have mistaken a necessary condition for a sufficient one.

### Structural validation versus semantic verification

Two different checks, often conflated because both are described as "checking the
citations."

Structural validation is deterministic and cheap. Does this file path appear in the
snapshot? Is this quoted span actually a substring of the pull request description? Is
this comment identifier one the model was shown? It catches a specific and important
failure — pointers to things that do not exist — and it catches it completely.

Semantic verification asks whether the evidence, granting that it exists, supports the
claim as stated. That question requires reading, so it is answered by a model, with the
claim and its cited material in hand, producing a verdict rather than a rewrite. It is
probabilistic, it costs roughly as much as producing the claim did, and it is not a
guarantee. It is a second opinion recorded next to the first.

### Provenance versus coverage

This is the distinction most often missing from systems that emphasize citations, and it
is the one that most affects whether a summary is fair.

Provenance answers: what supports this statement?

Coverage answers: how much of the work in scope contributed to this view?

A quarterly summary can consist entirely of well-evidenced, independently verifiable
claims and still leave a reader with a badly wrong impression, because the eleven pull
requests of unglamorous migration work were never mentioned. Every individual sentence
survives scrutiny. The omission is invisible precisely because there is nothing there to
scrutinize.

Coverage is only computable if the system knows the full set of candidate inputs for a
view, which requires recording that set rather than reconstructing it. Given the set and
the citation graph, it becomes an arithmetic question: of the pull requests eligible for
this view, which were cited by at least one claim, and which were not? The uncited list
is as much a part of the output as the narrative. A reader who sees "shipped the new
billing flow" alongside "34 of 51 pull requests in this window are not referenced by any
claim above" is in a substantially better position than one who sees the sentence alone.

### Abstraction versus grounding

Higher organizational altitude requires more compression. A director does not want forty
claims about individual pull requests, and producing them would not be a service. The
design objective is that raising the level of abstraction should not weaken the
evidential chain: a statement at director level should rest on the claims that were
synthesized into it, which in turn rest on atomic claims, which rest on specific evidence
in specific diffs. Abstraction moves; provenance persists through each level.

Whether that holds in practice — whether synthesis across several levels preserves enough
meaning to be worth reading, and whether the chain stays traversable and useful — is an
empirical question and one of the more uncertain parts of the proposal.

## 7. Describing work, not evaluating people

Altiscope is intended to describe engineering work. It is not intended to assess
individual performance, and the design excludes that use deliberately rather than
declining it rhetorically.

The reason is evidentiary. Pull request activity is a poor basis for judging a person.
It omits design work, mentoring, incident response, code review given to others,
recruiting, the work of not building something, and everything an engineer does that
never reaches a diff. It is systematically biased against people whose contributions are
diffuse and toward people whose contributions are legible. A system that produced
comparative judgments about individuals from this evidence would be confidently wrong in
a setting where being wrong has consequences for someone's career.

There is also an incentive argument. A system whose output feeds performance assessment
changes the behavior of the people it observes: pull requests are shaped for the
summarizer rather than for the reviewer, and the evidence base degrades. A system that
describes work has no such effect, or a much smaller one.

The boundary is therefore a product decision with architectural consequences: prompts
describe changes rather than characterize authors, comparative views are rendered side by
side from each person's own summaries rather than composed by a model asked to compare,
and evaluative language about individuals is treated as a defect.

## 8. Why pull requests

The pull request is a useful first unit for several reasons at once, which is unusual.

It is bounded. A merged pull request is finite and complete, so it can be read whole
rather than retrieved in fragments — which matters, because retrieval reintroduces
selective omission at the level where it is hardest to detect.

It is semantically rich. It contains the change, an account of why the change was made,
and the discussion of whether the change was right. Few other engineering artifacts carry
implementation and rationale in the same place.

It is a discrete event. A merged pull request does not change afterwards, which makes it a
natural unit for a summary computed once and reused, and a natural key for caching and
invalidation.

It is already reviewed. At least one other engineer looked at it, which is a weak but
real prior on coherence.

And it is machine-accessible through a stable API with a permission model organizations
already understand.

The limitation is important and not a detail: pull requests do not represent all
engineering work. Design documents, architectural decisions, operational work,
production debugging, direct pushes to a default branch, and work done in repositories
outside the system's view are all invisible. Any account built only from merged pull
requests is partial in ways that coverage reporting does not capture, because coverage
measures the fraction of *eligible inputs* that were used, not the fraction of *real
work* the inputs represent. This is a bounded first domain, chosen because it is
tractable, and the claim is about what can be built on it — not that it is sufficient.

## 9. Reader altitude

The same evidence base should be able to support different levels of synthesis for
different readers, chosen at the time the question is asked.

An engineer wants technical specifics and would be poorly served by themes. A team lead
wants workstreams with enough detail to spot trouble. A manager of leads wants the state
of those workstreams and technical detail only where it changes a decision. A director
wants themes across several teams and their consequences. An executive wants a handful of
statements, each resting on a large share of the underlying work.

These are genuinely different documents, and today they are produced by different people
at different times from different partial knowledge, which is why they routinely disagree
with each other. Generating them from one evidence base does not guarantee they agree,
but it makes disagreement detectable: two views of the same period can be compared
through their shared sources.

Higher altitude should mean more synthesis over the same facts, not a different factual
universe and not weaker grounding.

## 10. Query-time understanding

Organizational reporting is usually organized around a calendar — weekly updates, monthly
business reviews, quarterly summaries — because human compression is expensive enough
that it has to be batched. The calendar is an artifact of that cost, not a property of
the questions people actually have.

The questions people have are shaped by events: what happened in the two weeks around
the launch; what the migration actually involved; what changed in this repository between
the incident and the postmortem; what the three teams that were merged in June had been
working on separately. A system that has retained atomic accounts of work, each tied to
its evidence, can answer questions over arbitrary scopes and windows, because the
composition happens when the question is asked rather than when the calendar said to
compute a rollup.

This differs from a traditional reporting hierarchy in what it makes possible rather than
in how it looks. A stored weekly rollup can be read; it cannot be re-cut for a window
that does not align with it, and the connection from a quarter's sentence to the pull
requests behind it is usually gone. Composing on demand from atomic units preserves both.
It costs more per question, and it puts weight on the aggregation step: a composition
performed fresh for every question has to be reliable enough to be worth asking, which is
what the mechanisms in section 5 are for.

## 11. Possible implications

If the approach works, several things become possible. They are stated as possibilities
because none of them has been demonstrated.

Manual status reporting might decrease, or shift from producing a description to
reviewing and correcting one — which is a different and cheaper task.

Organizational memory might improve. An account of what a team did in a quarter two years
ago, with its evidence attached, is not something most organizations can produce today at
any price.

Leaders might understand technical work faster, and understand it in terms of what
changed rather than how much changed.

Cross-team understanding might become cheaper, since the cost of reading another team's
work would no longer be the cost of finding someone to explain it.

Views might be organized around events, launches or questions instead of reporting
periods.

A reader encountering a surprising statement might be able to follow it to the diff that
produced it, which changes the character of the conversation that follows.

And the evidence architecture — claims with validated pointers into stored source
material — may turn out to support analyses other than summarization. A compliance
finding or a quality observation has the same shape as a claim: a statement about a
change, with evidence, that can be verified and disputed. No such analysis exists, and
the possibility is noted here only to explain why the data model is shaped the way it is.

## 12. What this thesis does not claim

- That pull requests capture all engineering work. They capture a bounded and biased
  subset, described in section 8.
- That language models are reliably correct about code. The architecture assumes they are
  not, which is why validation, verification, coverage and human flags exist.
- That provenance guarantees correctness. It makes the basis of a claim inspectable.
- That verification guarantees correctness. It is a second opinion from a different
  model, and a second model can share the first one's misreading.
- That coverage guarantees a fair view. It measures the fraction of eligible inputs
  cited, which is a proxy for representativeness, not a measure of it.
- That management hierarchy becomes unnecessary. Altiscope addresses one function of one
  layer for one kind of work.
- That engineering performance can be inferred from GitHub activity. Section 7 argues it
  cannot.
- That any of this has been validated. The system is at the design and foundation stage;
  the end-to-end pipeline does not exist.
- That the current architecture is the final one. Several open questions could change it
  substantially; they are listed in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## 13. Hypotheses

The argument above reduces to a small number of claims that can be tested against real
repositories and real readers. Stated as hypotheses, in roughly the order they would be
tested:

1. **Sufficiency of the unit.** A merged pull request contains enough semantic evidence
   for a model to produce an atomic account that the engineer who wrote it judges
   accurate and complete enough to stand as a record.
2. **Inspectability through structure.** Requiring typed claims with validated evidence
   pointers, rather than prose, makes model interpretation inspectable enough that a
   reviewer can efficiently locate errors — and does so without suppressing so much
   content that the output stops being useful.
3. **Synthesis without unacceptable degradation.** Atomic claims can be composed to
   higher altitudes, including through intermediate levels, while remaining accurate and
   traceable to their sources.
4. **Verification yield.** Independent verification by a second model catches a
   meaningful class of errors that structural validation cannot — specifically, claims
   whose evidence exists but does not support them — at a rate that justifies its cost.
5. **Coverage as a signal.** Coverage measurement identifies selectively incomplete views
   that readers would otherwise accept, and readers change their conclusions when shown
   what was omitted.
6. **Altitude usefulness.** Altitude-specific synthesis produces output that readers at
   each level find more useful than the alternatives available to them, including the
   summary written for a different level.
7. **Net cost reduction.** The system reduces the total organizational cost of
   understanding engineering work, counting the effort of reviewing and correcting its
   output.

The first four are testable on a single repository with a modest set of human-reviewed
summaries. The last three require an organization using the system over a period long
enough for its habits to change, and are correspondingly harder to establish and easier
to fool oneself about.
