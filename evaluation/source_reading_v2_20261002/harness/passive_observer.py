"""Current production app with passive test observers; policies unchanged."""
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

import api.app
from core.engineering_context import EngineeringContextResolver
from core.engineering_planning import EngineeringEvidencePlanner
from core.engineering_retrieval import EngineeringRetrievalComponent
from core.engineering_verification import BoundEngineeringEvidenceVerifier
from core.tool_agent.executor import ToolExecutor

app = api.app.app
LOG = Path(os.environ["ASSESSMENT_OBSERVATIONS"])
local = threading.local()
lock = threading.Lock()


def write(stage, payload):
    record = {"run_id": getattr(local, "run_id", None), "stage": stage, "at": time.time(), **payload}
    with lock:
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


original_context = EngineeringContextResolver.resolve
def context(self, user_input, conversation_context):
    local.run_id = uuid4().hex
    started = time.monotonic()
    result = original_context(self, user_input, conversation_context)
    write("context", {"original_input": user_input, "resolved_input": result.resolved_input,
        "received_count": result.received_count, "used_count": result.used_count,
        "used_tokens": result.used_tokens, "truncated": result.truncated,
        "resolver_used": result.resolver_used, "resolver_fallback": result.resolver_fallback,
        "elapsed_ms": int((time.monotonic() - started) * 1000)})
    return result
EngineeringContextResolver.resolve = context

original_plan = EngineeringEvidencePlanner.plan
def plan(self, resolved_input):
    started = time.monotonic()
    result = original_plan(self, resolved_input)
    write("planner", {"plan": result.plan.to_dict(), "fallback_used": result.fallback_used,
        "failure_code": result.failure_code,
        "call_metadata": result.call_metadata.to_dict() if result.call_metadata else None,
        "elapsed_ms": int((time.monotonic() - started) * 1000)})
    return result
EngineeringEvidencePlanner.plan = plan

original_retrieve = EngineeringRetrievalComponent.retrieve
def retrieve(self, resolved_input, planner_outcome):
    started = time.monotonic()
    result = original_retrieve(self, resolved_input, planner_outcome)
    write("retrieval", {"route": result.route_decision.route,
        "strategy": result.route_decision.retrieval_strategy,
        "retrieval_call_count": result.retrieval_call_count,
        "required_query_ids": list(result.required_query_ids),
        "covered_query_ids": list(result.covered_query_ids),
        "knowledge_evidence_count": len(result.knowledge_evidence),
        "source_names": [e.source_name for e in result.knowledge_evidence],
        "elapsed_ms": int((time.monotonic() - started) * 1000)})
    return result
EngineeringRetrievalComponent.retrieve = retrieve

original_verify = BoundEngineeringEvidenceVerifier.verify
def verify(self, current_public_evidence, proposed_answer=None):
    result = original_verify(self, current_public_evidence, proposed_answer)
    write("verification", {"proposed_answer_present": proposed_answer is not None,
        "requirement_profile": self._requirement.requirement_profile.value,
        "requirement_satisfied": result.evidence_requirement_satisfied,
        "binding_required": result.answer_evidence_binding_required,
        "binding_status": result.answer_evidence_binding_status,
        "cited_evidence_ids": list(result.cited_evidence_ids),
        "insufficiency_reasons": list(result.insufficiency_reasons),
        "retrieval_can_generate": result.retrieval_can_generate,
        "can_finalize": result.can_finalize})
    return result
BoundEngineeringEvidenceVerifier.verify = verify

original_execute = ToolExecutor.execute
def execute(self, call, tool_call_allowed=True):
    started = time.monotonic()
    result = original_execute(self, call, tool_call_allowed)
    data = result.result or {}
    paths = []
    for key in ("matches", "changes", "candidates"):
        paths += [item.get("path") for item in data.get(key, []) if item.get("path")]
    span = {key: data.get(key) for key in ("path", "start_line", "end_line") if key in data}
    write("tool", {"tool": call.tool_name, "arguments": call.arguments_copy(),
        "status": result.status, "error_code": result.error_code,
        "returned_paths": paths, "span": span,
        "elapsed_ms": int((time.monotonic() - started) * 1000)})
    return result
ToolExecutor.execute = execute

# Follow-up diagnosis records only schema fields, never raw provider output.
import core.query_planning.openai_compatible as planner_provider
from core.query_planning.models import QueryPlan, Subquery
from core.query_planning.planner import PLANNER_MODEL_ALLOWED_FIELDS

original_parse = planner_provider.parse_planner_output
def observe_parse(*, original_query, raw_output):
    outcome = original_parse(original_query=original_query, raw_output=raw_output)
    details = {"failure_code": outcome.failure_code}
    try:
        obj = json.loads(raw_output)
        if isinstance(obj, dict):
            details["field_count"] = len(obj)
            details["extra_field_count"] = len(set(obj) - PLANNER_MODEL_ALLOWED_FIELDS)
            details["missing_field_count"] = len(PLANNER_MODEL_ALLOWED_FIELDS - set(obj))
            details["schema_fields"] = {
                key: value if type(value) is bool or type(value) is str and len(value) < 80 else type(value).__name__
                for key, value in obj.items()
                if key in {"query_type", "action", "retrieval_required", "reason_code"}
            }
            if set(obj) == PLANNER_MODEL_ALLOWED_FIELDS:
                try:
                    QueryPlan.create(original_query=original_query,
                        query_type=obj["query_type"], retrieval_required=obj["retrieval_required"],
                        action=obj["action"], reason_code=obj["reason_code"],
                        subqueries=tuple(Subquery.from_dict(item) for item in obj["subqueries"]))
                except (TypeError, ValueError) as exc:
                    details["schema_issue"] = str(exc)[:240]
    except (TypeError, ValueError):
        details["json_valid"] = False
    write("planner_schema_diagnostic", details)
    return outcome
planner_provider.parse_planner_output = observe_parse
