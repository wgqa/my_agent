"""One frozen document requirement variant per production-app process."""

import os
from pathlib import Path
import sys
import types

import core

snapshot = Path(os.environ["DOCUMENT_REQUIREMENT_SNAPSHOT"])
variant = types.ModuleType("core.engineering_requirements")
sys.modules[variant.__name__] = variant
core.engineering_requirements = variant
exec(compile(snapshot.read_text(encoding="utf-8"), str(snapshot), "exec"), variant.__dict__)

from evaluation.source_search_v6_20261003.harness import passive_observer as observer
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider
from core.engineering_verification import BoundEngineeringEvidenceVerifier

app = observer.app
original_verify = BoundEngineeringEvidenceVerifier.verify


def verify(self, current_public_evidence, proposed_answer=None):
    result = original_verify(self, current_public_evidence, proposed_answer)
    observer.write("requirement_identity", {
        "router_version": self._requirement.router_version,
        "profile": self._requirement.requirement_profile.value,
        "groups": [list(group) for group in self._requirement.required_evidence_groups],
    })
    return result


BoundEngineeringEvidenceVerifier.verify = verify
original_execute = ToolExecutor.execute


def execute(self, call, tool_call_allowed=True):
    result = original_execute(self, call, tool_call_allowed)
    if call.tool_name in {"code_search", "read_project_context"}:
        observer.write(
            "source_search" if call.tool_name == "code_search" else "source_read",
            {
                "arguments": call.arguments_copy(), "status": result.status,
                "error_code": result.error_code, "result": result.result,
            },
        )
    return result


ToolExecutor.execute = execute
original_decide = OpenAICompatibleAgentDecisionProvider.decide


def decide(self, *args, **kwargs):
    outcome = original_decide(self, *args, **kwargs)
    state = kwargs.get("control_state")
    observer.write("decision_metadata", {
        "metadata": outcome.call_metadata.to_dict() if outcome.call_metadata else None,
        "failure_code": outcome.failure_code,
        "selected_action": outcome.action.action if outcome.action else None,
        "control_state": state.to_dict(include_evidence_reference_control=True) if state else None,
    })
    return outcome


OpenAICompatibleAgentDecisionProvider.decide = decide
