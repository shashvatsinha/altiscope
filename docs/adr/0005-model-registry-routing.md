# ADR-0005: Model choice is a routing decision from a config registry

Status: proposed

## Context

Reading a single diff and synthesizing three hundred summaries into a narrative are
different tasks with different context and quality needs. Input size alone can force a
model change. Enterprises often mandate a provider (Bedrock, Vertex, Foundry, a gateway).
And the only trustworthy way to choose a model for this task is to compare real output
on real PRs, which requires knowing which model produced each summary and why.

## Decision

- `config/models.yaml` declares providers (an adapter kind plus an endpoint and the
  environment variable holding its key), models (provider, wire name, context window,
  max output, cost, capabilities) and per-stage routing: an ordered candidate list, an
  effort level, and a producer-independence rule for verification (`model` or
  `provider`).
- Two adapter kinds ship: `anthropic` (native structured output, caching, effort) and
  `openai_compatible`, which covers OpenAI, Azure OpenAI and every open-source serving
  stack that speaks the chat-completions protocol (Ollama, vLLM, llama.cpp, LM Studio)
  plus hosted gateways. A provider kind can be declared any number of times with
  different endpoints. Gemini is a third adapter of the same shape when needed.
- Models declare capabilities; the adapter picks the strongest structured-output mode
  available (`native`, `json_mode`, `prompt`) and records which it used. The pipeline's
  own validation against the snapshot is the correctness guarantee in every mode.
- The router returns a `RoutingDecision` with the chosen model and a plain-language
  `reason`. The decision is stored on `llm_calls` next to the prompt version hash, token
  usage, latency and request id.
- Providers implement a two-method protocol: `generate_structured` and `count_tokens`.
  Where a model has no token-count endpoint the count is a deliberate overestimate.
- Routing is by fit and preference only. No cost optimization logic in v1; the registry
  records cost so it can be reported, not so the router can trade quality for it
  silently.

## Rejected

- A multi-provider abstraction library. Broad coverage, but a fast-moving API surface
  and lowest-common-denominator support for structured outputs. Two adapters (native
  Anthropic, chat-completions protocol) reach the same set of models with less to
  maintain; a third for Gemini is small.
- Hardcoding one model per stage. Fine for a week, then someone needs Bedrock.

## Consequences

- Swapping a model for a stage is a config change and a cache invalidation, and both
  old and new outputs remain in the database for comparison.
- Token counting goes through the provider so an exact count is used where one exists;
  elsewhere a conservative character-based estimate keeps plans small.
- Pluggable is not trusted. Any model can be routed to; only the golden set (ADR-0007)
  says whether it should be a stage default.
