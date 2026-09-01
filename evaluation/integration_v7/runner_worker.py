"""One isolated, safe worker for ARCH-EVAL-08B.

The parent runner supplies one frozen case and one isolated system checkout.
This process imports ``core`` only after putting that checkout first on the
import path, performs one provider-backed run, and emits a bounded JSON
summary.  It never writes evaluation artifacts and never serializes prompts,
raw provider output, observations, credentials, or local paths.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping


WORKER_SCHEMA_VERSION = "integration_v7_real_dev_worker_v1"
PROVIDER = "deepseek"
MODEL = "deepseek-chat"
UNIFIED_DECISION_PROMPT_SELECTOR = "engineering_agent_decision_prompt_unified_v1"


def _bootstrap_system_imports(system_root: Path) -> None:
    script_root = Path(__file__).resolve().parents[2]
    excluded = {script_root, system_root}
    cleaned: list[str] = []
    for entry in sys.path:
        try:
            resolved = Path(entry or Path.cwd()).resolve()
        except OSError:
            continue
        if resolved not in excluded:
            cleaned.append(entry)
    sys.path[:] = [str(system_root), *cleaned]


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


class _RecordingRetrievalPort:
    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self.calls: list[dict[str, Any]] = []

    @property
    def supported_strategies(self):
        return tuple(getattr(self._delegate, "supported_strategies", ()))

    def search(self, query: str, strategy: str, top_k: int):
        started = time.perf_counter()
        documents = tuple(self._delegate.search(query, strategy, top_k))
        self.calls.append(
            {
                "strategy": strategy,
                "top_k": top_k,
                "returned_count": len(documents),
                "source_names": [
                    document.source_name
                    for document in documents
                    if isinstance(getattr(document, "source_name", None), str)
                ],
                "latency_ms": _ms(started),
            }
        )
        return documents


class _RecordingResolver:
    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self.call_attempts = 0
        self.fallback = False

    def resolve(self, history, question):
        if history:
            self.call_attempts += 1
        resolution = self._delegate.resolve(history, question)
        self.fallback = bool(getattr(resolution, "fallback", False))
        return resolution


class _TimedContextResolver:
    def __init__(self, resolver_cls, query_resolver: object) -> None:
        self._resolver = resolver_cls(query_resolver)
        self.snapshot = None
        self.latency_ms = 0.0

    def resolve(self, user_input: str, conversation_context):
        started = time.perf_counter()
        snapshot = self._resolver.resolve(user_input, conversation_context)
        self.latency_ms += _ms(started)
        self.snapshot = snapshot
        return snapshot


class _RecordingPlanner:
    def __init__(self, base_cls, delegate: object) -> None:
        self._base = base_cls
        self._delegate = delegate
        self.outcome = None
        self.latency_ms = 0.0

    def plan(self, original_query: str):
        started = time.perf_counter()
        outcome = self._delegate.plan(original_query)
        self.latency_ms += _ms(started)
        self.outcome = outcome
        return outcome


class _TimedRetrievalComponent:
    def __init__(self, component_cls, retrieval_port: object) -> None:
        self._component = component_cls(retrieval_port)
        self.snapshot = None
        self.latency_ms = 0.0

    def retrieve(self, resolved_input: str, planner_outcome):
        started = time.perf_counter()
        snapshot = self._component.retrieve(resolved_input, planner_outcome)
        self.latency_ms += _ms(started)
        self.snapshot = snapshot
        return snapshot


class _TimedExecutionAdapter:
    def __init__(self, adapter_cls, runtime: object) -> None:
        self._adapter = adapter_cls(runtime)
        self.latency_ms = 0.0

    def run(self, *args, **kwargs):
        started = time.perf_counter()
        result = self._adapter.run(*args, **kwargs)
        self.latency_ms += _ms(started)
        return result


class _TimedBoundVerifier:
    def __init__(self, bound: object, owner: "_TimedVerifier") -> None:
        self._bound = bound
        self._owner = owner

    def verify(self, current_public_evidence, proposed_answer=None):
        if proposed_answer is not None:
            started = time.perf_counter()
            result = self._bound.verify(current_public_evidence, proposed_answer)
            self._owner.finalization_latency_ms += _ms(started)
            return result
        return self._bound.verify(current_public_evidence, proposed_answer)


class _TimedVerifier:
    def __init__(self, verifier_cls) -> None:
        self._verifier = verifier_cls()
        self.latency_ms = 0.0
        self.finalization_latency_ms = 0.0

    def bind(self, planner_outcome, retrieval_snapshot, requirement):
        return _TimedBoundVerifier(
            self._verifier.bind(planner_outcome, retrieval_snapshot, requirement),
            self,
        )

    def verify(
        self,
        planner_outcome,
        retrieval_snapshot,
        requirement,
        current_public_evidence,
        *,
        proposed_answer=None,
    ):
        started = time.perf_counter()
        result = self._verifier.verify(
            planner_outcome,
            retrieval_snapshot,
            requirement,
            current_public_evidence,
            proposed_answer=proposed_answer,
        )
        self.latency_ms += _ms(started)
        return result


def _safe_trace(result: object) -> list[dict[str, Any]]:
    allowed = {
        "iteration",
        "event_type",
        "action_type",
        "tool_name",
        "call_id",
        "tool_status",
        "error_code",
        "iterations_used",
        "tool_calls_used",
        "tool_errors_used",
        "provider_call_count",
        "repair_attempted",
        "repair_succeeded",
        "parse_failure_category",
        "guard_status",
        "missing_evidence_groups",
        "distinct_project_code_paths",
        "required_min_distinct_project_code_paths",
    }
    trace = []
    for event in getattr(result, "trace", ()):
        data = event.to_dict()
        trace.append({key: value for key, value in data.items() if key in allowed})
    return trace


def _safe_evidence(result: object) -> list[dict[str, Any]]:
    return [item.to_dict() for item in getattr(result, "evidence", ())]


def _safe_result(result: object) -> dict[str, Any]:
    return {
        "status": result.status,
        "answer": result.answer,
        "reason_code": result.reason_code,
        "failure_code": result.failure_code,
        "iterations_used": result.iterations_used,
        "tool_calls_used": result.tool_calls_used,
        "tool_errors_used": result.tool_errors_used,
        "trace": _safe_trace(result),
        "evidence": _safe_evidence(result),
    }


def _safe_planner(outcome: object, latency_ms: float) -> dict[str, Any]:
    if outcome is None:
        return {
            "llm_calls": 0,
            "fallback_used": False,
            "failure_code": None,
            "latency_ms": round(latency_ms, 3),
        }
    metadata = outcome.call_metadata
    return {
        "llm_calls": metadata.call_count if metadata is not None else 0,
        "fallback_used": outcome.fallback_used,
        "failure_code": outcome.failure_code,
        "action": outcome.plan.action,
        "query_type": outcome.plan.query_type,
        "subquery_count": len(outcome.plan.subqueries),
        "latency_ms": round(latency_ms, 3),
    }


def _knowledge_source_hit(case: Mapping[str, Any], calls: list[Mapping[str, Any]]) -> bool | None:
    expected = set(case.get("knowledge_gold_sources") or ())
    if not expected:
        return None
    observed = {
        source
        for call in calls
        for source in call.get("source_names", ())
    }
    return bool(expected & observed)


def _safe_retrieval(
    case: Mapping[str, Any],
    calls: list[dict[str, Any]],
    snapshot: object | None,
    result: object,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "calls": [
            {
                key: value
                for key, value in call.items()
                if key != "latency_ms"
            }
            for call in calls
        ],
        "retrieval_call_count": len(calls),
        "knowledge_source_hit_at_5": _knowledge_source_hit(case, calls),
        "hybrid_rescue_attempted": False,
        "hybrid_rescue_used": False,
        "subquery_coverage": None,
        "merged_evidence_count": sum(
            1 for item in getattr(result, "evidence", ()) if item.kind == "knowledge"
        ),
    }
    if snapshot is not None:
        required = tuple(snapshot.required_query_ids)
        covered = tuple(snapshot.covered_query_ids)
        output.update(
            {
                "retrieval_call_count": snapshot.retrieval_call_count,
                "query_count": snapshot.query_count,
                "required_query_ids": list(required),
                "covered_query_ids": list(covered),
                "subquery_coverage": (
                    len(covered) / len(required) if required else 1.0
                ),
                "hybrid_rescue_attempted": snapshot.upgrade_attempted,
                "hybrid_rescue_used": snapshot.upgrade_used,
                "merged_evidence_count": len(snapshot.evidence_bundle.items),
                "route": snapshot.route_decision.route,
            }
        )
    return output


def _context_payload(
    case: Mapping[str, Any],
    system: str,
    snapshot: object | None,
    resolver: _RecordingResolver | None,
) -> dict[str, Any]:
    received = snapshot.received_count if snapshot is not None else 0
    used = snapshot.used_count if snapshot is not None else 0
    return {
        "input_mode": (
            "frozen_conversation_context" if system == "B" and case.get("conversation_context") else "question_only"
        ),
        "received_count": received,
        "used_count": used,
        "used_tokens": snapshot.used_tokens if snapshot is not None else 0,
        "truncated": snapshot.truncated if snapshot is not None else False,
        "resolver_used": snapshot.resolver_used if snapshot is not None else False,
        "resolver_fallback": snapshot.resolver_fallback if snapshot is not None else False,
        "resolution_correct": (
            None
            if case.get("task_family") != "context_followup"
            else bool(
                snapshot is not None
                and snapshot.resolved_input.strip()
                == case["expected_standalone_intent"].strip()
            )
            if system == "B"
            else None
        ),
        "llm_calls": resolver.call_attempts if resolver is not None else 0,
    }


def _classify_infrastructure(
    result: object,
    resolver: _RecordingResolver | None,
    planner_outcome: object | None,
) -> str | None:
    if resolver is not None and resolver.fallback:
        return "provider_error"
    if planner_outcome is not None and planner_outcome.failure_code in {
        "PLANNER_PROVIDER_ERROR",
        "PLANNER_TIMEOUT",
    }:
        return (
            "provider_timeout"
            if planner_outcome.failure_code == "PLANNER_TIMEOUT"
            else "provider_error"
        )
    if result.failure_code in {"ACTION_PROVIDER_ERROR", "ACTION_TIMEOUT"}:
        return (
            "provider_timeout"
            if result.failure_code == "ACTION_TIMEOUT"
            else "provider_error"
        )
    return None


def _select_decision_prompt_profile(job: Mapping[str, Any]):
    """Select a worker profile without changing the frozen default.

    Existing 08B/09B jobs omit ``decision_prompt_profile_selector`` and remain
    bound to V2.  Only the explicit B'' candidate selector may import the
    newer profile; unknown selectors and selectors on the A path fail closed.
    """

    selector = job.get("decision_prompt_profile_selector")
    if selector is None:
        from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_V2_PROFILE

        return ENGINEERING_DECISION_PROMPT_V2_PROFILE
    if job.get("system") != "B" or selector != UNIFIED_DECISION_PROMPT_SELECTOR:
        raise ValueError("unsupported decision prompt profile selector")
    from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE

    return ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE


def _run(job: Mapping[str, Any]) -> dict[str, Any]:
    system = job["system"]
    system_root = Path(job["system_root"]).resolve()
    target_root = Path(job["target_root"]).resolve()
    corpus_root = Path(job["corpus_root"]).resolve()
    _bootstrap_system_imports(system_root)

    try:
        decision_prompt_profile = _select_decision_prompt_profile(job)
    except (ImportError, ValueError):
        return {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "execution_validity": "INVALID",
            "infrastructure_code": "unsupported_decision_prompt_profile",
        }

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "execution_validity": "INVALID",
            "infrastructure_code": "missing_environment",
        }

    from core.engineering_knowledge import build_verified_engineering_knowledge
    from core.engineering_requirements import (
        evaluate_evidence_requirement,
        route_engineering_evidence_requirement,
    )
    from core.tool_agent.integration import build_tool_agent_runtime

    knowledge = build_verified_engineering_knowledge(
        corpus_root,
        repo_root=system_root,
    )
    retrieval_port = _RecordingRetrievalPort(knowledge.retrieval_port)
    question = job["question"]
    case = job["case"]
    start = time.perf_counter()
    context_snapshot = None
    resolver_recorder = None
    planner_recorder = None
    retrieval_component = None
    verifier = None
    toolagent_latency = 0.0

    if system == "A":
        runtime = build_tool_agent_runtime(
            repo_root=target_root,
            retrieval_port=retrieval_port,
            api_key=api_key,
            prompt_profile=decision_prompt_profile,
        )
        runtime.latency_ms = 0.0
        original_runtime_run = runtime.run

        def timed_runtime_run(*args, **kwargs):
            started = time.perf_counter()
            result = original_runtime_run(*args, **kwargs)
            runtime.latency_ms += _ms(started)
            return result

        runtime.run = timed_runtime_run
        requirement = route_engineering_evidence_requirement(question)
        result = runtime.run(
            question,
            evidence_requirement=requirement,
        )
        toolagent_latency = runtime.latency_ms
    else:
        from core.conversation_context import OpenAICompatibleConversationQueryResolver
        from core.engineering_agent import EngineeringAgentFacade
        from core.engineering_context import EngineeringContextResolver as ContextResolver
        from core.engineering_planning import EngineeringEvidencePlanner
        from core.engineering_retrieval import EngineeringRetrievalComponent
        from core.engineering_verification import EngineeringEvidenceVerifier
        from core.query_planning import BaseQueryPlanner, OpenAICompatibleQueryPlanner
        from core.generator.deepseek_gen import DEEPSEEK_BASE_URL
        from core.unified_engineering_runtime import (
            LegacyToolAgentExecutionAdapter,
            UnifiedEngineeringRuntime,
        )

        # The import above is intentionally resolved from the System B checkout.
        # The package-level context resolver is the existing resolver provider;
        # EngineeringContextResolver is the bounded Runtime component.
        resolver_provider = OpenAICompatibleConversationQueryResolver(
            provider=PROVIDER,
            model=MODEL,
            api_key=api_key,
            base_url=DEEPSEEK_BASE_URL,
        )
        resolver_recorder = _RecordingResolver(resolver_provider)
        context_component = ContextResolver(resolver_recorder)
        context_component.latency_ms = 0.0
        context_component.snapshot = None
        original_context_resolve = context_component.resolve

        def timed_context_resolve(user_input, conversation_context):
            started = time.perf_counter()
            snapshot = original_context_resolve(user_input, conversation_context)
            context_component.latency_ms += _ms(started)
            context_component.snapshot = snapshot
            return snapshot

        context_component.resolve = timed_context_resolve
        planner_provider = OpenAICompatibleQueryPlanner(
            provider=PROVIDER,
            model=MODEL,
            api_key=api_key,
            base_url=DEEPSEEK_BASE_URL,
        )
        class RecordingPlanner(BaseQueryPlanner):
            def __init__(self, delegate):
                self._delegate = delegate
                self.outcome = None
                self.latency_ms = 0.0

            def plan(self, original_query):
                started = time.perf_counter()
                outcome = self._delegate.plan(original_query)
                self.latency_ms += _ms(started)
                self.outcome = outcome
                return outcome

        planner_recorder = RecordingPlanner(planner_provider)
        planner_component = EngineeringEvidencePlanner(planner_recorder)
        retrieval_component = EngineeringRetrievalComponent(retrieval_port)
        retrieval_component.latency_ms = 0.0
        retrieval_component.snapshot = None
        original_retrieve = retrieval_component.retrieve

        def timed_retrieve(resolved_input, planner_outcome):
            started = time.perf_counter()
            snapshot = original_retrieve(resolved_input, planner_outcome)
            retrieval_component.latency_ms += _ms(started)
            retrieval_component.snapshot = snapshot
            return snapshot

        retrieval_component.retrieve = timed_retrieve
        tool_runtime = build_tool_agent_runtime(
            repo_root=target_root,
            retrieval_port=retrieval_port,
            api_key=api_key,
            base_url=DEEPSEEK_BASE_URL,
            prompt_profile=decision_prompt_profile,
        )
        execution_adapter = LegacyToolAgentExecutionAdapter(tool_runtime)
        execution_adapter.latency_ms = 0.0
        original_adapter_run = execution_adapter.run

        def timed_adapter_run(*args, **kwargs):
            started = time.perf_counter()
            result = original_adapter_run(*args, **kwargs)
            execution_adapter.latency_ms += _ms(started)
            return result

        execution_adapter.run = timed_adapter_run
        verifier = EngineeringEvidenceVerifier()
        verifier.latency_ms = 0.0
        verifier.finalization_latency_ms = 0.0
        original_verifier_verify = verifier.verify

        def timed_verifier_verify(
            planner_outcome,
            retrieval_snapshot,
            requirement,
            current_public_evidence,
            *,
            proposed_answer=None,
        ):
            started = time.perf_counter()
            result = original_verifier_verify(
                planner_outcome,
                retrieval_snapshot,
                requirement,
                current_public_evidence,
                proposed_answer=proposed_answer,
            )
            verifier.latency_ms += _ms(started)
            return result

        verifier.verify = timed_verifier_verify
        original_verifier_bind = verifier.bind

        def timed_verifier_bind(planner_outcome, retrieval_snapshot, requirement):
            bound = original_verifier_bind(
                planner_outcome,
                retrieval_snapshot,
                requirement,
            )
            return _TimedBoundVerifier(bound, verifier)

        verifier.bind = timed_verifier_bind
        unified_runtime = UnifiedEngineeringRuntime(
            execution_adapter,
            context_resolver=context_component,
            evidence_planner=planner_component,
            retrieval_component=retrieval_component,
            evidence_verifier=verifier,
        )
        facade = EngineeringAgentFacade(unified_runtime)
        result = facade.run(
            question,
            conversation_context=job.get("conversation_context", []),
        )
        toolagent_latency = execution_adapter.latency_ms
        context_snapshot = context_component.snapshot
        requirement = route_engineering_evidence_requirement(
            context_snapshot.resolved_input
        )

    result_payload = _safe_result(result)
    trace = result_payload["trace"]
    tool_sequence = [
        event["tool_name"]
        for event in trace
        if event.get("event_type") == "tool_call_created" and event.get("tool_name")
    ]
    planner_outcome = planner_recorder.outcome if planner_recorder is not None else None
    if context_snapshot is not None:
        context_latency = getattr(context_component, "latency_ms", 0.0)
    else:
        context_latency = 0.0
    planner_latency = planner_recorder.latency_ms if planner_recorder is not None else 0.0
    retrieval_snapshot = retrieval_component.snapshot if retrieval_component is not None else None
    retrieval_latency = retrieval_component.latency_ms if retrieval_component is not None else 0.0
    verifier_latency = verifier.latency_ms if verifier is not None else 0.0
    finalization_latency = verifier.finalization_latency_ms if verifier is not None else 0.0
    decision_calls = sum(
        event.get("provider_call_count", 0)
        for event in trace
        if event.get("event_type") == "decision_completed"
    )
    repair_calls = sum(
        1
        for event in trace
        if event.get("event_type") == "decision_completed"
        and event.get("repair_attempted")
    )
    context_payload = _context_payload(case, system, context_snapshot, resolver_recorder)
    planner_payload = _safe_planner(planner_outcome, planner_latency)
    retrieval_payload = _safe_retrieval(
        case,
        retrieval_port.calls,
        retrieval_snapshot,
        result,
    )
    requirement_state = evaluate_evidence_requirement(requirement, result.evidence)
    requirement_contract_match = (
        tuple(requirement.required_evidence_groups)
        == tuple(tuple(group) for group in case["required_evidence_groups"])
        and requirement.min_distinct_project_code_paths
        == case["min_distinct_project_code_paths"]
    )
    infrastructure_code = _classify_infrastructure(
        result,
        resolver_recorder,
        planner_outcome,
    )
    return {
        "worker_schema_version": WORKER_SCHEMA_VERSION,
        "execution_validity": "INVALID" if infrastructure_code else "VALID",
        "infrastructure_code": infrastructure_code,
        "result": result_payload,
        "context": context_payload,
        "planner": planner_payload,
        "retrieval": retrieval_payload,
        "timing": {
            "latency_e2e_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "latency_context_ms": round(context_latency, 3),
            "latency_planner_ms": round(planner_latency, 3),
            "latency_retrieval_ms": round(retrieval_latency, 3),
            "latency_toolagent_ms": round(toolagent_latency, 3),
            "latency_verifier_ms": round(verifier_latency, 3),
            "latency_finalization_ms": round(finalization_latency, 3),
        },
        "requirement_state": requirement_state.to_dict(),
        "requirement_contract_match": requirement_contract_match,
        "llm_calls_context": context_payload["llm_calls"],
        "llm_calls_planner": planner_payload["llm_calls"],
        "llm_calls_toolagent_decision": decision_calls,
        "llm_calls_repair": repair_calls,
        "llm_calls_total": (
            context_payload["llm_calls"]
            + planner_payload["llm_calls"]
            + decision_calls
            + repair_calls
        ),
        "token_usage": "UNAVAILABLE",
        "tool_sequence": tool_sequence,
    }


def main() -> int:
    try:
        job = json.loads(sys.stdin.read())
        if not isinstance(job, dict):
            raise ValueError
        payload = _run(job)
    except Exception:
        payload = {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "execution_validity": "INVALID",
            "infrastructure_code": "worker_execution_failure",
        }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
