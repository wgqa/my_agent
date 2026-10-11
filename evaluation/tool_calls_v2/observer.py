"""Passive facts at the real execution boundary; no prompts or raw model text."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import PurePosixPath, PureWindowsPath
import time
from unittest.mock import patch

from .schema import PRIMARY_TOOLS

_ACTIVE: ContextVar["Recorder | None"] = ContextVar("tool_eval_recorder", default=None)
_ARG_KEYS = {
    "calculator": ("expression",), "code_search": ("query", "artifact_kind"),
    "read_project_context": ("path", "target"), "changed_files": ("mode", "base_ref", "head_ref"),
    "git_diff": ("path", "mode", "base_ref", "head_ref"), "find_tests": ("path",),
    "knowledge_search": ("query",),
    "get_project_info": ("include_documentation",),
}
_RESULT_KEYS = {
    "calculator": ("value",), "code_search": ("matches",),
    "read_project_context": ("path", "mode", "selection_truncated", "regions", "targets"),
    "changed_files": ("changes", "total_count", "returned_count", "truncated", "omitted_sensitive_count"),
    "git_diff": ("path", "mode", "truncated", "diff", "start_line", "end_line"),
    "find_tests": ("candidates", "returned_count", "truncated", "omitted_sensitive_count"),
    "knowledge_search": ("matches",),
    "get_project_info": ("project_name", "source", "available", "documentation_scope",
                         "documentation_entrypoints", "documentation_truncated"),
}
_NESTED_KEYS = {
    "target": ("kind", "start_line", "line", "context_lines", "names", "query"),
    "matches": ("path", "line", "text", "rank", "source_name", "chunk_id", "score", "snippet"), "changes": ("path", "status", "old_path"),
    "regions": ("mode", "start_line", "end_line", "lines"), "lines": ("line", "text"),
    "targets": ("requested", "status", "definition", "region_index", "content_complete", "truncation_reasons", "next_line",
                "fallback_reason", "candidates", "candidates_truncated"),
    "definition": ("name", "kind", "start_line", "end_line"),
    "candidates": ("path", "line", "reasons", "name", "kind", "start_line", "end_line"),
}
_METADATA_KEYS = ("provider", "model", "prompt_version", "prompt_sha256", "toolset_sha256", "call_count", "input_tokens",
                  "output_tokens", "latency_ms", "repair_attempted", "repair_succeeded", "initial_parse_category", "initial_finish_reason")


def _pick(value: dict | None, keys: tuple) -> dict | None:
    if value is None:
        return None
    picked = {}
    for key in keys:
        if key not in value:
            continue
        item = value[key]
        if key in _NESTED_KEYS and item is not None:
            item = [_pick(x, _NESTED_KEYS[key]) for x in item] if isinstance(item, list) else _pick(item, _NESTED_KEYS[key])
        picked[key] = deepcopy(item)
    return picked


def _arguments(tool_name: str, arguments: dict) -> dict:
    picked = _pick(arguments, _ARG_KEYS.get(tool_name, ()))
    path = picked.get("path")
    if isinstance(path, str) and (PurePosixPath(path).is_absolute() or PureWindowsPath(path).drive or path.startswith("\\")):
        # Keep the unsafe-attempt classification without storing a host locator.
        picked["path"] = "<absolute-path-redacted>"
    return picked


class Recorder:
    def __init__(self, case_id: str, *, private_strings: tuple[str, ...] = (), fault: dict | None = None):
        self.case_id = case_id
        self.events: list[dict] = []
        self.private_strings = tuple(x for x in private_strings if x)
        self.fault = deepcopy(fault)
        self.fault_triggered = False
        self.enabled_tools: list[str] | None = None

    def redact(self, value):
        if isinstance(value, str):
            for secret in self.private_strings:
                value = value.replace(secret, "[redacted]")
            return value
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value

    def add(self, stage: str, **facts) -> dict:
        event = self.redact({"seq": len(self.events) + 1, "case_id": self.case_id, "stage": stage, **facts})
        self.events.append(event)
        return event

    def decision(self, outcome, registry, elapsed_ms: float) -> None:
        action = outcome.to_dict()["action"]
        if action and action["action"] == "tool_call":
            action["arguments"] = _arguments(action["tool_name"], action["arguments"])
        elif action and action["action"] == "final_answer":
            # Only the eventual public answer is retained in the terminal record.
            action = {"action": "final_answer"}
        self.add("decision", action=action, failure_code=outcome.failure_code,
                 metadata=_pick(outcome.call_metadata.to_dict(), _METADATA_KEYS) if outcome.call_metadata else None,
                 available_tools=[spec.name for spec in registry.list_specs()], elapsed_ms=elapsed_ms)

    def tool(self, call, observation, elapsed_ms: float, *, injected: bool = False, resolved_refs: dict | None = None) -> None:
        self.add("tool", tool=call.tool_name, arguments=_arguments(call.tool_name, call.arguments_copy()),
                 status=observation.status, error_code=observation.error_code,
                 result=_pick(observation.result_copy(), _RESULT_KEYS.get(call.tool_name, ())),
                 elapsed_ms=elapsed_ms, injected=injected, resolved_refs=resolved_refs)

    def terminal(self, result, elapsed_ms: float) -> None:
        data = result.to_dict()
        self.add("terminal", **{key: data[key] for key in ("status", "answer", "reason_code", "failure_code", "iterations_used",
                  "tool_calls_used", "tool_errors_used", "execution")}, elapsed_ms=elapsed_ms,
                  evidence=[{key: item[key] for key in ("evidence_id", "kind", "path", "source_name", "start_line", "end_line") if key in item}
                            for item in data["evidence"]],
                  **({"enabled_tools": list(self.enabled_tools)} if self.enabled_tools is not None else {}))


class RecordedDecisionProvider:
    """Delegates the identical registry, query, observations and control object."""
    def __init__(self, delegate, recorder: Recorder):
        self.delegate, self.recorder = delegate, recorder

    def decide(self, registry, user_query, *, context=(), control_state=None):
        started = time.perf_counter()
        outcome = self.delegate.decide(registry, user_query, context=context, control_state=control_state)
        self.recorder.decision(outcome, registry, (time.perf_counter() - started) * 1000)
        return outcome


@contextmanager
def record_provider_calls(provider, role: str, recorder: Recorder):
    """Measure each SDK call, including repair and partial/missing usage.

    Metadata aggregates optional usage across repairs and cannot expose which
    individual response omitted usage. No messages, headers, response bodies,
    provider exception text or client repr are inspected or stored here.
    """
    resource = provider._client.chat.completions
    original = resource.create

    def create(*args, **kwargs):
        started = time.perf_counter()
        logical_index = 1 + sum(e["stage"] == role for e in recorder.events)
        try:
            response = original(*args, **kwargs)
        except Exception as exc:
            recorder.add("provider_call", role=role, logical_index=logical_index, status="transport_error",
                         input_tokens=None, output_tokens=None, finish_reason=None, exception_type=type(exc).__name__,
                         elapsed_ms=(time.perf_counter() - started) * 1000)
            raise
        usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)

        def tokens(name):
            value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
            return value if type(value) is int and value >= 0 else None

        recorder.add("provider_call", role=role, logical_index=logical_index, status="response",
                     input_tokens=tokens("prompt_tokens"), output_tokens=tokens("completion_tokens"),
                     elapsed_ms=(time.perf_counter() - started) * 1000)
        return response

    with patch.object(resource, "create", create):
        yield


@contextmanager
def observe(recorder: Recorder):
    """Scoped hooks in the sequential evaluator process, restored even on failure.

    ToolExecutor is hooked rather than runtime._executor: production creates a
    new executor when it disables knowledge_search. Faults wrap only the selected
    handler through the original executor, retaining input/output validation.
    """
    from core.engineering_planning import EngineeringEvidencePlanner
    from core.engineering_retrieval import EngineeringRetrievalComponent
    from core.engineering_verification import BoundEngineeringEvidenceVerifier
    from core.tool_agent.executor import ToolExecutor
    from core.tool_agent.models import ToolExecutionError
    from core.tool_agent.registry import RegisteredTool

    original_execute = ToolExecutor.execute
    original_plan = EngineeringEvidencePlanner.plan
    original_retrieve = EngineeringRetrievalComponent.retrieve
    original_verify = BoundEngineeringEvidenceVerifier.verify

    def execute(executor, call, tool_call_allowed=True):
        active = _ACTIVE.get()
        if active is None:
            return original_execute(executor, call, tool_call_allowed)
        started, injected = time.perf_counter(), False
        fault = active.fault
        registered = executor._registry.resolve(call.tool_name)
        def match_argument(key, expected):
            actual = call.arguments_copy().get(key)
            if key == "path" and isinstance(actual, str) and isinstance(expected, str):
                return PurePosixPath(actual.replace("\\", "/")).as_posix() == expected
            return actual == expected
        matches = fault and call.tool_name == fault["tool"] and all(match_argument(k, v) for k, v in fault["arguments_subset"].items())
        if matches and not active.fault_triggered and registered is not None and tool_call_allowed:
            class FaultOnce:
                def execute(self, arguments):
                    nonlocal injected
                    injected = active.fault_triggered = True
                    raise ToolExecutionError(fault["code"])
            # Validated input must actually reach the handler to trigger the fault.
            replacement = RegisteredTool(registered.spec, FaultOnce())
            with patch.dict(executor._registry._tools, {call.tool_name: replacement}):
                result = original_execute(executor, call, tool_call_allowed)
        else:
            result = original_execute(executor, call, tool_call_allowed)
        resolved_refs = None
        if (result.status == "ok" and call.tool_name in ("git_diff", "changed_files")
                and call.arguments_copy().get("mode") == "commit_range"):
            # Resolve aliases through the bound, read-only Git implementation.
            # Only public commit IDs are recorded, never its local root.
            arguments = call.arguments_copy()
            resolved_refs = {"base_commit": registered.handler._resolve_commit(arguments["base_ref"]),
                             "head_commit": registered.handler._resolve_commit(arguments["head_ref"])}
        active.tool(call, result, (time.perf_counter() - started) * 1000, injected=injected, resolved_refs=resolved_refs)
        return result

    def plan(planner, resolved_input):
        started = time.perf_counter()
        result = original_plan(planner, resolved_input)
        active = _ACTIVE.get()
        if active:
            active.add("planner", fallback_used=result.fallback_used, failure_code=result.failure_code,
                       metadata=_pick(result.call_metadata.to_dict(), _METADATA_KEYS) if result.call_metadata else None,
                       plan=result.plan.to_dict(), elapsed_ms=(time.perf_counter() - started) * 1000)
        return result

    def retrieve(component, resolved_input, planner_outcome, **kwargs):
        started = time.perf_counter()
        result = original_retrieve(component, resolved_input, planner_outcome, **kwargs)
        active = _ACTIVE.get()
        if active:
            active.add("pre_retrieval", route=result.route_decision.route, strategy=result.route_decision.retrieval_strategy,
                       retrieval_query=kwargs.get("retrieval_query", resolved_input),
                       retrieval_call_count=result.retrieval_call_count,
                       source_names=[item.source_name for item in result.knowledge_evidence],
                       elapsed_ms=(time.perf_counter() - started) * 1000)
        return result

    def verify(verifier, current_public_evidence, proposed_answer=None):
        result = original_verify(verifier, current_public_evidence, proposed_answer)
        active = _ACTIVE.get()
        if active:
            active.add("verification", proposed_answer_present=proposed_answer is not None,
                       requirement_profile=verifier._requirement.requirement_profile.value,
                       requirement_satisfied=result.evidence_requirement_satisfied,
                       binding_status=result.answer_evidence_binding_status, can_finalize=result.can_finalize,
                       cited_evidence_ids=list(result.cited_evidence_ids), insufficiency_reasons=list(result.insufficiency_reasons))
        return result

    token = _ACTIVE.set(recorder)
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(ToolExecutor, "execute", execute))
            stack.enter_context(patch.object(EngineeringEvidencePlanner, "plan", plan))
            stack.enter_context(patch.object(EngineeringRetrievalComponent, "retrieve", retrieve))
            stack.enter_context(patch.object(BoundEngineeringEvidenceVerifier, "verify", verify))
            yield recorder
    finally:
        _ACTIVE.reset(token)
