# ADR-0005: Model choice is a routing decision from a config registry

Status: proposed

## Context

Reading a single diff and synthesizing three hundred summaries into a narrative are
different tasks with different context and quality needs. Input size alone can force a
model change. Enterprises often mandate a provider (Bedrock, Vertex, Foundry, a gateway).
And the only trustworthy way to choose a model for this task is to compare real output
on real PRs, which requires knowing which model produced each summary and why.

## Decision

- `config/models.yaml` declares models (provider, context window, max output, cost) and
  per-stage routing: a default, an ordered candidate list, an effort level, and optional
  constraints such as "verifier must differ from producer".
- The router returns a `RoutingDecision` with the chosen model and a plain-language
  `reason`. The decision is stored on `llm_calls` next to the prompt version hash, token
  usage, latency and request id.
- Providers implement a two-method protocol: `generate_structured` (schema-constrained
  output) and `count_tokens`. The Anthropic adapter is first. Others are config plus one
  adapter file each.
- Routing is by fit and preference only. No cost optimization logic in v1; the registry
  records cost so it can be reported, not so the router can trade quality for it
  silently.

## Rejected

- A multi-provider abstraction library. Broad coverage, fast-moving API surface, and
  lowest-common-denominator support for structured outputs, which is the one feature
  this system depends on most.
- Hardcoding one model per stage. Fine for a week, then someone needs Bedrock.

## Consequences

- Swapping a model for a stage is a config change and a cache invalidation, and both
  old and new outputs remain in the database for comparison.
- Token counting for routing goes through the provider so the count matches the model
  that will run; a character-based heuristic is used only for planning when no provider
  is available.
