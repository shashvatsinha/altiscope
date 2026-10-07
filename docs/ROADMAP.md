# Roadmap

Each milestone delivers a complete demonstrable outcome. Implementation PRs target a
milestone integration branch. Main advances only after the full demo, checks and review;
component completion alone does not authorize a release.

1. [One change, explained — #4](https://github.com/shashvatsinha/altiscope/issues/4).
   Public PR ingestion, immutable snapshots, PR-linked review publication, provider-neutral
   generation and provenance, CLI inspection and a credential-free demo. Implementation
   children [#11](https://github.com/shashvatsinha/altiscope/issues/11) through
   [#17](https://github.com/shashvatsinha/altiscope/issues/17). The owner accepted M1 and merged PRs #20, #22, and #23;
   see the [walkthrough](M1-WALKTHROUGH.md) and [release evidence](releases/m1.md).
2. [One repository, understood — #5](https://github.com/shashvatsinha/altiscope/issues/5).
   Date-window collection, summaries at different levels of detail, and drill-down through
   saved report versions to all underlying PRs. Preserve model/prompt history; updates
   happen on request using the latest successful inputs. Implementation, repeatable
   demos, and review fixes #31 through #34 passed their checks. The owner accepted the
   engineer and manager samples for inclusion on 2026-09-10.
   See the [walkthrough](M2-WALKTHROUGH.md), [release evidence](releases/m2.md), and [ADR-0011](adr/0011-aggregate-report-provenance.md).
3. [Different models, measurable results — #6](https://github.com/shashvatsinha/altiscope/issues/6).
   Versioned recipes, optional independent whole-result assessment, model comparisons,
   and a real-source workflow demonstration with exact results and review history.
   Released on 2026-10-06 as a workflow demonstration, not a qualified quality
   result. See [M3 release evidence](releases/m3.md) and [ADR-0013](adr/0013-m3-workflow-release-scope.md).
4. [A local web application — #7](https://github.com/shashvatsinha/altiscope/issues/7).
   Run on a laptop or desktop, bound to localhost, without login or public access.
   Select a repository, date range, and engineer/manager/executive detail level;
   generate or open code-grounded reports and navigate exact input versions and PR links.
   Use a server-side GitHub token for accessible public and private repositories.
   Support repository discovery or owner/name entry, permission errors, cached results,
   empty windows, generation progress/failure, and bounded generation cost.
   Ship local setup, accessible pages, API/UI checks, and an owner-reviewed walkthrough.
   Required children: #85–#93, #96, #98–#100. Feedback #94 is optional.
   Expert-review UI #95 and study #97 are deferred and do not block release.
5. [A hosted application with repository connections — #8](https://github.com/shashvatsinha/altiscope/issues/8).
   Public-facing deployment with login and GitHub App authorization for selected
   repositories, including private ones. A demo visitor can connect their own work.
   Enforce user/repository isolation throughout report history, caches, and source
   navigation; handle installation changes and revocation. Add hosted spend controls
   and job handling needed for reliable use. Broader temporal team membership and
   recurring refresh automation remain follow-ups, not prerequisites to this workflow.
6. [A system that improves through use — #9](https://github.com/shashvatsinha/altiscope/issues/9).
   Feedback, corrections and continuous measured improvement.
7. [An enterprise-ready deployment — #10](https://github.com/shashvatsinha/altiscope/issues/10).
   Operational hardening and deployment controls.

Later milestones are decomposed after their dependencies pass. No employee evaluation.

[ADR-0014](adr/0014-local-web-and-hosted-access.md) records the owner-approved
local-first scope. Qualified studies remain optional future work, with no M4/M5 gate.
