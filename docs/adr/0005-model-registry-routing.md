# ADR-0005: Configure model selection in a registry

Status: proposed

## Context

Describing one pull request and combining hundreds of summaries have different input
sizes and quality requirements. Organizations may also require particular model
services. Configuration lets them choose models without changing pipeline code.

## Decision

- Declare providers, models, and per-stage preferences in `config/models.yaml`.
  A provider specifies an adapter, endpoint, and API-key environment variable. A model
  specifies its provider, API name, context and output limits, prices, and capabilities.
- Use two adapters: `anthropic` and `openai_compatible` for compatible chat-completions
  endpoints. The same adapter kind can serve several configured endpoints. A native
  Gemini adapter could be added later.
- Select structured-output mode from declared capabilities: `native`, `json_mode`, then
  `prompt`. Record the mode used and check evidence references separately. Neither
  schema validation nor reference validation establishes that a claim is accurate.
- Route to the first eligible model with room for the estimated input. Configure effort
  per stage. For verification, `model` excludes the producing model and `provider`
  excludes its configured provider.
- Return a `RoutingDecision` with the chosen model and reason. Store it on `llm_calls`
  with the prompt hash, usage, latency, and request ID when storage is implemented.
- Providers implement `generate_structured` and `count_tokens`. Use a token-count
  endpoint where supported; otherwise estimate from character count.
- Use prices for cost reporting. Routing follows capacity and preference, without
  automatic cost optimization.

## Alternatives considered

- **A multi-provider library.** Could offer broader coverage, but adds a dependency and
  may not expose the structured-output features needed here. Direct adapters keep
  those protocol choices visible, at the cost of maintaining them ourselves.
- **Hardcode one model per stage.** This would require code changes to switch models
  or deployment endpoints.

## Consequences

- Changing a stage's model is a configuration change. The planned cache must distinguish
  models and retain older outputs for comparison.
- Endpoint compatibility depends on the server and its settings. A registry entry alone
  does not establish compatibility or output quality.
- Character-based token estimates can be too low or too high. Complete-request budgeting
  and handling oversized requests still need work.
- Different models or providers may share errors. Evaluate defaults on human-reviewed
  examples; that evaluation workflow remains unbuilt.
