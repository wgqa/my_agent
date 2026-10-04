"""Both arms use v4/v7; only the bounded test-reading prompt policy differs."""

import os
from pathlib import Path
import sys
import types

arm = os.environ["TEST_ACQUISITION_ARM"]
if arm not in {"baseline", "candidate"}:
    raise ValueError("Unknown definition-policy arm")
# Reuse the passive observers, with the prior slice's candidate assembly in
# both arms. The prompt override occurs before FastAPI enters its lifespan.
os.environ["TEST_ACQUISITION_ARM"] = "candidate"
from evaluation.project_test_acquisition_20261003 import comparison_server as shared
import api.app as application
from core.tool_agent.decision_prompt import DecisionPromptProfile

if arm == "baseline":
    snapshot = Path(__file__).resolve().parent / "baseline/decision_prompt.py"
    variant = types.ModuleType("_test_acquisition_phase1_prompt")
    sys.modules[variant.__name__] = variant
    exec(compile(snapshot.read_bytes(), str(snapshot), "exec"), variant.__dict__)
    profile = variant.ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_V2_PROFILE
    application.ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_V2_PROFILE = DecisionPromptProfile(
        version=profile.version, sha256=profile.sha256, template=profile.template,
        render_control_state=True, render_evidence_reference_control=True,
    )

app = shared.app

# Diagnose failed tool arguments without recording raw actions, paths, queries,
# answers, or any provider secret. Parsing and execution policies are untouched.
import json
from jsonschema import Draft202012Validator
import core.tool_agent.openai_compatible as provider_module

original_diagnose = provider_module.diagnose_agent_action_text


def diagnose(text, registry):
    result = original_diagnose(text, registry)
    if result.category and result.category.value == "ARGUMENTS_SCHEMA_INVALID":
        try:
            obj = json.loads(text)
            spec = registry.get_spec(obj.get("tool_name"))
            arguments = obj.get("arguments", {})
            if spec and type(arguments) is dict:
                errors = list(Draft202012Validator(spec.input_schema).iter_errors(arguments))
                safe = {}
                for key, value in arguments.items():
                    if key in {"mode", "artifact_kind"} and type(value) is str:
                        safe[key] = value if value in {"window", "definition", "any", "project_code", "project_doc", "project_test"} else "unknown_enum"
                    elif key in {"line", "start_line", "context_lines"} and type(value) is int:
                        safe[key] = value
                shared.observer.write("argument_schema_diagnostic", {
                    "tool": spec.name, "argument_keys": sorted(arguments), "safe_parameters": safe,
                    "violations": [{"validator": e.validator, "path": list(e.absolute_path)} for e in errors],
                })
        except Exception as exc:
            shared.observer.write("argument_diagnostic_unavailable", {"error_type": type(exc).__name__})
    return result


provider_module.diagnose_agent_action_text = diagnose
