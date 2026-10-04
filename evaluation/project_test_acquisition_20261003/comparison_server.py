"""Production assembly, with a frozen pre-slice Router in the baseline arm."""

import os
from pathlib import Path
import sys
import types

arm = os.environ["TEST_ACQUISITION_ARM"]
if arm not in {"baseline", "candidate"}:
    raise ValueError("Unknown test acquisition arm")
if arm == "baseline":
    import core
    snapshot = Path(__file__).resolve().parent / "baseline/core/engineering_requirements.py"
    variant = types.ModuleType("core.engineering_requirements")
    sys.modules[variant.__name__] = variant
    core.engineering_requirements = variant
    exec(compile(snapshot.read_bytes(), str(snapshot), "exec"), variant.__dict__)

import api.app as application
from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_PROFILE
from core.tool_agent.tools.code_search import CODE_SEARCH_VERSION

if arm == "baseline":
    application.ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_V2_PROFILE = (
        ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_PROFILE
    )
    application.CODE_SEARCH_TEST_VERSION = CODE_SEARCH_VERSION

from evaluation.source_search_v6_20261003.harness import passive_observer as observer
from core.engineering_verification import BoundEngineeringEvidenceVerifier
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider

app = observer.app
original_execute = ToolExecutor.execute


def execute(self, call, tool_call_allowed=True):
    result = original_execute(self, call, tool_call_allowed)
    if call.tool_name in {"code_search", "read_project_context", "find_tests", "calculator"}:
        observer.write("tool_result", {
            "tool": call.tool_name, "arguments": call.arguments_copy(),
            "status": result.status, "error_code": result.error_code, "result": result.result,
        })
    return result


ToolExecutor.execute = execute
original_decide = OpenAICompatibleAgentDecisionProvider.decide


def decide(self, *args, **kwargs):
    result = original_decide(self, *args, **kwargs)
    observer.write("decision_metadata", {
        "metadata": result.call_metadata.to_dict() if result.call_metadata else None,
        "failure_code": result.failure_code,
        "selected_action": result.action.action if result.action else None,
    })
    return result


OpenAICompatibleAgentDecisionProvider.decide = decide
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
