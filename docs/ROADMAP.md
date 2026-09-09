# Roadmap

Each milestone delivers a complete demonstrable outcome. Implementation PRs target a
milestone integration branch. Main advances only after the full demo, checks and review;
component completion alone does not authorize a release.

1. [One change, explained — #4](https://github.com/shashvatsinha/altiscope/issues/4).
   Public PR ingestion, immutable snapshots, PR-linked review publication, provider-neutral
   generation and provenance, CLI inspection and a credential-free demo. Implementation
   children [#11](https://github.com/shashvatsinha/altiscope/issues/11) through
   [#17](https://github.com/shashvatsinha/altiscope/issues/17). Implementation under review;
   see the [walkthrough](M1-WALKTHROUGH.md) and [release evidence](releases/m1.md).
2. [One repository, understood — #5](https://github.com/shashvatsinha/altiscope/issues/5).
   Date-window collection, summaries at different levels of detail, and drill-down through
   saved report versions to all underlying PRs. Preserve model/prompt history; updates
   happen on request using the latest successful inputs. Implementation and repeatable
   demos are ready for review; sample review and release integration remain pending.
   See the [walkthrough](M2-WALKTHROUGH.md), [release evidence](releases/m2.md), and [ADR-0011](adr/0011-aggregate-report-provenance.md).
3. [Different models, measurable results — #6](https://github.com/shashvatsinha/altiscope/issues/6).
   Versioned recipes, optional second-model verification, model comparisons and a
   human-reviewed 20-PR evaluation set with held-out examples.
4. [A product people can explore — #7](https://github.com/shashvatsinha/altiscope/issues/7).
   Public hosted UI/API demo with evidence navigation and feedback.
5. [A team's working tool — #8](https://github.com/shashvatsinha/altiscope/issues/8).
   GitHub App, private access, authorization, temporal membership and background work.
6. [A system that improves through use — #9](https://github.com/shashvatsinha/altiscope/issues/9).
   Feedback, corrections and continuous measured improvement.
7. [An enterprise-ready deployment — #10](https://github.com/shashvatsinha/altiscope/issues/10).
   Operational hardening and deployment controls.

Later milestones are decomposed after their dependencies pass. No employee evaluation.
