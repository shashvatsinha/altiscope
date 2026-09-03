# ADR-0001: Python for the backend

Status: proposed

## Context

The hard parts of Altiscope are ingestion fidelity, prompt design, structured-output
validation, evaluation against human feedback, and a provenance data model. None of
them are UI problems. The team working on it will iterate on prompts and evaluation far
more often than on request handling.

## Options

- **Python.** Strongest LLM tooling (official SDKs with structured-output helpers,
  pydantic for schemas that double as validation and JSON schema). Fast iteration on
  prompts and evals. Weaker at single-binary distribution; type safety depends on
  discipline (pyright strict, pydantic at boundaries).
- **TypeScript.** One language for a richer UI and the backend; LLM SDKs are good. Data
  and eval tooling is thinner. The "one language" advantage only pays if a SPA is built
  early, which ADR-0008 and the architecture argue against.
- **Go.** Best deployment story (single static binary, low memory), good GitHub client
  libraries. Structured output and prompt iteration are noticeably slower to work with;
  the eval loop would be written from scratch.

## Decision

Python 3.11+, `pyright` in strict mode, `ruff`, pydantic v2 models for every LLM
boundary, `uv` for dependency management. The web layer is FastAPI with server-rendered
templates for v1; the JSON API is the primary contract so a separate front end can be
added without touching the core.

## Consequences

- Deployment is a container, not a binary. Acceptable for the target audience, which
  already runs containers.
- Typing discipline must be enforced in CI from day one or it decays. `pyright` strict
  is in the CI workflow.
- If a rich SPA becomes necessary, it lives in a separate package consuming the API;
  this is a deliberate boundary, not an accident.
