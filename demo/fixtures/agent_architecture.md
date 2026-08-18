# Agent Architecture

This release demo fixture describes the structured agent stages without being an
evaluation dataset.

## Query Decomposition

Query decomposition turns a complex question into a small set of focused
subqueries. Each subquery can target a different evidence obligation, such as a
mechanism, a comparison, or an implementation detail.

## Adaptive Retrieval

Adaptive retrieval chooses a retrieval strategy from the plan and the runtime
capabilities. A simple fact can use one retrieval call; a decomposed question
can retrieve each required subquery and merge the evidence deterministically.

## Verifier

The verifier checks whether required query or evidence targets are covered. If
coverage is incomplete, the runtime can refuse to generate a grounded answer
instead of presenting unsupported content as fact.

## Structured Tool Agent

A structured tool agent chooses from an allowlisted set of tools. The runtime
executes a validated tool call, records a safe observation, and may use that
observation for a bounded next decision. Tool policy and budgets remain system
controls rather than user-provided parameters.

## Tool Observation

A tool observation is untrusted data returned by a tool. It is passed back as
structured input for the next decision, but raw model output, prompts, keys, and
traceback details are not exposed in the public safe trace.
