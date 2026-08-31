# Unified Runtime Context Migration

> Task: `ARCH-CONTEXT-03`
> Date: 2026-08-31
> Status: **CURRENT**

## 1. What problem does conversation context solve?

Users often ask follow-ups such as “它怎么实现？” or “那这个改动会影响
什么？”. A bounded recent context lets the Engineering Agent resolve the
follow-up into a standalone retrieval question before evidence planning and
Tool execution. It improves continuity without turning the product into an
unbounded memory system.

This is different from exposing history as a public evaluator or API control
field. The current public Engineering request remains question-only; context
is an internal Runtime seam.

## 2. Recent context is not long-term memory

Recent context is short-lived input supplied for one run. Long-term memory
would require persistence, summarization, relevance retrieval, lifecycle and
privacy policy. G8 only supports the first, bounded category. The project
therefore does not infer that a recent-context result justifies Vector Memory
or persistent sessions.

## 3. The G8 bound

`RecentContextWindow` keeps at most the newest 6 messages and at most 1200
tokens. It selects newest-first and evicts older messages when the budget is
full. It does not summarize, reorder, or silently drop malformed messages.

The bounded result records the received count, used count, used tokens and
truncation flag. `EngineeringContextSnapshot` also records the original and
resolved inputs, resolver usage and fallback state. Selected message content is
excluded from the snapshot representation so ordinary logging cannot print it.

## 4. Standalone query resolver

For non-empty bounded history, the existing
`OpenAICompatibleConversationQueryResolver` may make at most one
OpenAI-compatible call. Its frozen operational settings are temperature `0`,
maximum output `160`, and retry `0`. An empty history makes zero provider
calls.

The resolver rewrites the follow-up into one JSON standalone query. It does
not answer the question, select tools, plan retrieval, or own a loop.

## 5. One resolved query downstream

`EngineeringContextResolver` produces one `EngineeringContextSnapshot`. The
Unified Runtime takes only `snapshot.resolved_input` and sends that same value
to both:

1. the Engineering requirement router, exactly once; and
2. the ToolAgent execution adapter and its Decision provider.

There is no split where the router sees the original question while the Agent
sees the resolved question. The context resolver is a component, not an Agent.

## 6. Failure semantics

Expected provider or response-shape failures are represented by the existing
resolver as a safe fallback to the original input. The run continues, and the
failure is not converted into a Tool failure or a ToolAgent error counter.

An unknown programming error, such as an unexpected `RuntimeError`, propagates
without a catch-all fallback. This preserves debuggability and avoids hiding
implementation defects as ordinary provider unavailability.

## 7. Budget and controller boundary

The standalone resolver call is not a ToolAgent iteration, Tool call, Tool
error, or second ledger. `ToolAgentRuntime` remains the only bounded
Decision → Tool → Observation loop during this migration and continues to
enforce the frozen 5/4/2 limits. The final architecture has one logical budget
owner in Execution Policy; the migration adapter does not add another.

## 8. API and observability boundary

The three Engineering endpoints (`/engineering/query`, v1 stream and v2
stream) continue to pass `conversation_context=None`, and
`EngineeringQueryRequest` still contains only `question`. Gate 3 `/agent/query`
and Gate 4 `/tool-agent/query` are unchanged.

Safe Trace and Rich Activity contain allowlisted lifecycle metadata only. They
do not receive conversation content, resolver prompts, provider errors, raw
responses or traceback text. Observability remains a read-only projection and
cannot change the runtime outcome.

## 9. G8 conclusion and migration trade-off

The historical G8 conclusion remains **MIXED / USEFUL BUT NOT GENERAL**. The
component migration does not claim that recent context is universally useful;
it makes the bounded capability available at the correct control-plane seam so
later evaluations can measure it without creating a second Agent.

The main trade-off is that the migration temporarily keeps a legacy execution
component and adapters. That is preferable to a big-bang rewrite because each
future stage can be regression-tested and attributed independently, while Gate
facts and sealed/formal conclusions remain unchanged.

## 10. Two-minute interview explanation

“We had a bounded G8 recent-context window and a standalone-query resolver,
but they lived on an older AgentRuntime path while the Engineering product was
actually controlled by ToolAgentRuntime. I migrated them as a thin Context
Resolver component at the front of one Unified Engineering Runtime. It keeps
six messages and 1200 tokens, calls the resolver at most once, and sends the
same resolved query to requirement routing and ToolAgent execution. Expected
provider failures fall back to the original question; programming bugs
propagate. The resolver is not an Agent and does not own budget or a loop. The
existing ToolAgentRuntime remains the sole 5/4/2 execution loop during
migration, so we avoid nested controllers and can later migrate G3 components
one by one.”

## 11. Common design mistakes

- Passing the original question to the router but the resolved question to the
  ToolAgent, creating inconsistent requirements.
- Calling the resolver once per downstream component instead of once per run.
- Counting the resolver provider call as a ToolAgent iteration or adding a
  second resolver budget.
- Catching every exception and silently treating programming bugs as provider
  fallback.
- Logging the selected messages, resolver prompt, raw provider response or
  provider error text in Trace/Activity.
- Exposing `history`, `messages`, `memory`, or `session_id` in the public
  question-only Engineering request.
- Reimplementing `RecentContextWindow` or changing its 6-message/1200-token
  semantics during wiring.
- Wrapping `ToolAgentRuntime` in another autonomous AgentRuntime.
- Treating the mixed G8 result as proof that long-term memory is needed.
- Rewriting Gate 2/Gate 3 sealed facts or re-running Formal merely because a
  component moved into a new control plane.
