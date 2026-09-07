# ADR-0001: Python for the backend

Status: proposed

## Context

Early work focuses on collecting source material, preparing AI input, checking output,
and evaluating summaries. Python provides SDKs and data tools for this work.

## Options

- **Python.** Official model SDKs and Pydantic support structured output and validation.
  Type checking requires tools such as pyright; deployment requires a Python runtime.
- **TypeScript.** Could share a language between the backend and an interactive web
  interface. That benefit matters less while the interface remains unbuilt.
- **Go.** Offers single-binary distribution and GitHub client libraries. The proposed
  prompt and evaluation workflow would need different tooling.

## Decision

Use Python 3.11+, pyright in strict mode, ruff, Pydantic v2 at model boundaries, and uv
for dependencies. Propose FastAPI with server-rendered templates for the first web
interface, with a JSON API that a separate frontend could use later.

## Consequences

- Deploy in a container with the Python runtime.
- Enforce type checks in CI; strict pyright checking is already configured.
- A richer frontend would be a separate package consuming the API.

The Python foundation exists. The web service and interface remain unbuilt, and the
[architecture](../ARCHITECTURE.md#10-open-questions) keeps the interface choice open.
