# Study Note: Provider-Port-01

## Scope

`OpenAICompatibleProviderConfig` is a small transport boundary for the
Resolver, Planner, and ToolAgent Decision Provider. It describes public
connection metadata; it is not a provider registry, agent framework, or
benchmark identity.

## Key distinctions

- A provider identifies the service boundary and API compatibility contract;
  a model identifies the model selected behind that boundary. They are
  independent dimensions, so changing a model is not the same experiment as
  changing a provider.
- A/B results cannot be mixed across providers. Provider behavior, routing,
  latency, limits, and failure semantics can differ even when the model name
  is the same; comparisons must preserve provider and model identity.
- The OpenAI-compatible boundary carries `base_url`, `model`, and bounded
  public `extra_headers` to the SDK client. The API key is resolved from
  `api_key_env` only at client construction and is not configuration identity.
- `base_url` selects the compatible transport endpoint; `model` selects the
  requested model; `api_key_env` names the process environment entry from
  which the caller may obtain credentials; headers carry only non-secret
  transport metadata.
- `x-opencode-session` is work-unit scoped. The upper layer creates one
  bounded stable session ID for a case/work unit and injects it into the
  Resolver, Planner, and Decision clients. Components do not create a UUID per
  call, which keeps one work unit auditable without making the session a
  secret.

The historical DeepSeek defaults remain the default when no explicit config
is supplied. OpenCode Go is an explicit development profile, not a replacement
for the frozen Integration-v7 provider/model or its results.
