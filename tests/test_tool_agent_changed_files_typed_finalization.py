from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.engineering_requirements import route_engineering_evidence_requirement
from core.tool_agent.actions import (
    ACTION_PARSE_FAILED,
    ActionValidationError,
    AgentDecisionOutcome,
    ChangedFilesFinalizationAction,
    FinalAnswerAction,
    ToolCallAction,
    parse_action_object,
)
from core.tool_agent.changed_files_typed_finalization import (
    SelectorCallMetadata,
    _validate_source,
    selector_outcome_from_response,
)
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.tools.git_change import CHANGED_FILES_SPEC
from tests._engineering_runtime_support import (
    EmptyRetrievalPort,
    NoRetrievalPlanner,
    build_full_unified_runtime,
)


def _observation(changes=(), *, total=None, truncated=False, omitted=0):
    changes = list(changes)
    total_count = len(changes) if total is None else total
    return {
        "changes": changes,
        "total_count": total_count,
        "returned_count": len(changes),
        "truncated": truncated,
        "omitted_sensitive_count": omitted,
    }


class StaticChangedFilesHandler:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def execute(self, arguments):
        self.calls += 1
        return self.result


def _metadata():
    return SelectorCallMetadata(
        provider="fake",
        model="fake-model",
        prompt_sha256="a" * 64,
        input_tokens=30,
        output_tokens=10,
        latency_ms=1.0,
    )


def _selector_outcome(selector):
    return selector_outcome_from_response(
        json.dumps(selector), call_metadata=_metadata()
    )


class ScriptedTypedProvider:
    """Fake for the real Runtime seam; choices are fixtures, not LLM evidence."""

    def __init__(self, decisions, selector_responses=()):
        self.decisions = list(decisions)
        self.selector_responses = list(selector_responses)
        self.decision_calls = 0
        self.selector_calls = 0
        self.selector_inputs = []
        self.control_states = []

    def decide(self, registry, user_query, *, context=(), control_state=None):
        self.control_states.append(control_state)
        item = self.decisions[min(self.decision_calls, len(self.decisions) - 1)]
        self.decision_calls += 1
        return AgentDecisionOutcome(action=item, failure_code=None, call_metadata=None)

    def select_changed_files(self, user_query, *, execution, evidence_requirement):
        self.selector_calls += 1
        self.selector_inputs.append((user_query, execution, evidence_requirement))
        return self.selector_responses[self.selector_calls - 1]


def _run(
    query,
    changes,
    selector_response,
    *,
    answer="我已经检查了变更文件。",
    total=None,
    truncated=False,
    tool_arguments=None,
):
    handler = StaticChangedFilesHandler(
        _observation(changes, total=total, truncated=truncated)
    )
    registry = ToolRegistry()
    registry.register(CHANGED_FILES_SPEC, handler)
    provider = ScriptedTypedProvider(
        [
            ToolCallAction(
                action="tool_call",
                tool_name="changed_files",
                arguments=tool_arguments or {"mode": "working_tree"},
            ),
            FinalAnswerAction(action="final_answer", answer=answer),
        ],
        [selector_response],
    )
    runtime = ToolAgentRuntime(registry=registry, provider=provider)
    unified = build_full_unified_runtime(
        runtime,
        planner=NoRetrievalPlanner(),
        retrieval_port=EmptyRetrievalPort(),
    )
    return unified.run(query), provider, handler


def _run_direct(query, changes, final_action, *, tool_arguments=None):
    handler = StaticChangedFilesHandler(_observation(changes))
    registry = ToolRegistry()
    registry.register(CHANGED_FILES_SPEC, handler)
    provider = ScriptedTypedProvider(
        [
            ToolCallAction(
                action="tool_call",
                tool_name="changed_files",
                arguments=tool_arguments or {"mode": "working_tree"},
            ),
            final_action,
        ]
    )
    runtime = ToolAgentRuntime(registry=registry, provider=provider)
    unified = build_full_unified_runtime(
        runtime,
        planner=NoRetrievalPlanner(),
        retrieval_port=EmptyRetrievalPort(),
        finalization_strategy="direct_hybrid",
    )
    return unified.run(query), provider, handler


def test_direct_hybrid_uses_decision_typed_action_without_selector_call():
    result, provider, handler = _run_direct(
        "列出当前工作区所有变更文件",
        [
            {"path": "src/a.py", "status": "modified"},
            {"path": "src/deleted.py", "status": "deleted"},
        ],
        ChangedFilesFinalizationAction(
            action="changed_files_finalization",
            evidence_id="E1",
            operation="list_all",
        ),
    )
    assert result.status == "completed"
    assert "src/a.py" in result.answer and "src/deleted.py" in result.answer
    assert provider.decision_calls == 2
    assert provider.selector_calls == 0
    assert handler.calls == 1
    final_state = provider.control_states[-1]
    assert final_state.finalization_strategy == "direct_hybrid"
    assert [item.evidence_id for item in final_state.available_evidence_refs] == ["E1"]
    assert result.execution.selector_llm_calls == 0


def test_direct_hybrid_accepts_known_json_type_marker_but_not_wrong_eid():
    typed = parse_action_object(
        {
            "action": "changed_files_finalization",
            "type": "json_object",
            "evidence_id": "E1",
            "operation": "list_all",
        }
    )
    assert typed == ChangedFilesFinalizationAction(
        action="changed_files_finalization", evidence_id="E1", operation="list_all"
    )
    with pytest.raises(ActionValidationError):
        parse_action_object(
            {
                "action": "changed_files_finalization",
                "type": "wrong-kind",
                "evidence_id": "E1",
                "operation": "list_all",
            }
        )

    result, provider, _ = _run_direct(
        "列出当前工作区所有变更文件",
        [{"path": "src/a.py", "status": "modified"}],
        ChangedFilesFinalizationAction(
            action="changed_files_finalization",
            evidence_id="E99",
            operation="list_all",
        ),
    )
    assert result.status == "refused"
    assert result.answer is None
    assert provider.selector_calls == 0


def test_direct_hybrid_open_text_uses_lightweight_current_source_check():
    answer = "目前只能看到 src/main.py 的差异，无法比较其余文件的重要性。[E1]"
    result, provider, _ = _run_direct(
        "结合变更判断哪些最重要",
        [{"path": "src/main.py", "status": "modified"}],
        FinalAnswerAction(action="final_answer", answer=answer),
    )
    assert result.status == "completed"
    assert result.answer == answer
    assert provider.selector_calls == 0
    assert all(
        item.action != "changed_files_finalization"
        for item in provider.decisions
        if hasattr(item, "action")
    )


def test_direct_hybrid_open_answer_rejects_unknown_eid_without_legacy_binding():
    result, provider, _ = _run_direct(
        "结合变更判断哪些最重要",
        [{"path": "src/main.py", "status": "modified"}],
        FinalAnswerAction(
            action="final_answer", answer="主要变更在 src/main.py。[E99]"
        ),
    )
    assert result.status == "refused"
    assert result.answer is None
    assert provider.selector_calls == 0


def test_direct_hybrid_does_not_bypass_project_code_requirement():
    result, provider, _ = _run_direct(
        "列出已删除的源码文件",
        [{"path": "src/deleted.py", "status": "deleted"}],
        ChangedFilesFinalizationAction(
            action="changed_files_finalization",
            evidence_id="E1",
            operation="filter_status",
            status="deleted",
        ),
    )
    assert result.status == "refused"
    assert result.answer is None
    assert provider.selector_calls == 0


@pytest.mark.parametrize(
    "query,changes,selector,expected_fragments",
    [
        (
            "列出当前工作区所有变更文件",
            [
                {"path": "src/a.py", "status": "modified"},
                {"path": "src/new.py", "status": "renamed", "old_path": "src/old.py"},
            ],
            {"evidence_id": "E1", "operation": "list_all"},
            ("src/a.py", "modified", "src/old.py", "src/new.py"),
        ),
        (
            "列出已删除的文件",
            [
                {"path": "src/deleted.py", "status": "deleted"},
                {"path": "src/kept.py", "status": "modified"},
            ],
            {"evidence_id": "E1", "operation": "filter_status", "status": "deleted"},
            ("src/deleted.py", "deleted"),
        ),
        (
            "列出所有 modified 文件",
            [
                {"path": "src/a.py", "status": "modified"},
                {"path": "src/b.py", "status": "modified"},
                {"path": "src/c.py", "status": "deleted"},
            ],
            {"evidence_id": "E1", "operation": "filter_status", "status": "modified"},
            ("src/a.py", "src/b.py", "modified"),
        ),
        (
            "列出重命名文件",
            [{"path": "src/new.py", "status": "renamed", "old_path": "src/old.py"}],
            {"evidence_id": "E1", "operation": "filter_status", "status": "renamed"},
            ("src/old.py", "src/new.py", "→"),
        ),
        (
            "列出未跟踪文件",
            [{"path": "notes/new.md", "status": "untracked"}],
            {"evidence_id": "E1", "operation": "filter_status", "status": "untracked"},
            ("notes/new.md", "untracked"),
        ),
    ],
)
def test_real_unified_runtime_executes_typed_changed_files_finalization(
    query, changes, selector, expected_fragments
):
    result, provider, handler = _run(query, changes, _selector_outcome(selector))

    assert result.status == "completed"
    assert result.answer
    assert all(fragment in result.answer for fragment in expected_fragments)
    assert handler.calls == 1
    assert provider.decision_calls == 2
    assert provider.selector_calls == 1
    assert provider.selector_inputs[0][1].observation.status == "ok"
    assert provider.selector_inputs[0][1].observation.tool_name == "changed_files"
    assert provider.selector_inputs[0][1].evidence.evidence_id == "E1"
    assert provider.selector_inputs[0][1].evidence.granularity == "status_list"
    assert result.execution.selector_llm_calls == 1
    assert result.execution.selector_latency_ms == 1.0
    assert result.execution.input_tokens == 30
    assert result.execution.output_tokens == 10
    assert result.tool_calls_used == 1
    assert result.iterations_used == 2


def test_empty_complete_inventory_explains_scope_success_and_completeness():
    result, provider, _ = _run(
        "列出当前工作区所有变更文件",
        [],
        _selector_outcome({"evidence_id": "E1", "operation": "list_all"}),
    )
    assert result.status == "completed"
    assert "working_tree" in result.answer
    assert "成功检查" in result.answer
    assert "清单为空" in result.answer
    assert "结果完整" in result.answer
    assert "未发现可见变更文件" in result.answer
    assert provider.selector_calls == 1


def test_empty_complete_status_filter_is_distinguished_from_source_failure():
    result, provider, handler = _run(
        "列出已删除的文件",
        [{"path": "src/a.py", "status": "modified"}],
        _selector_outcome(
            {"evidence_id": "E1", "operation": "filter_status", "status": "deleted"}
        ),
    )
    assert handler.calls == 1
    assert result.status == "completed"
    assert "deleted 状态项" in result.answer
    assert "0 项" in result.answer
    assert "完整清单中" in result.answer
    assert "没有符合条件的可见变更文件" in result.answer
    assert provider.selector_calls == 1


def test_truncated_observation_is_delivered_only_as_explicit_partial_result():
    result, _, _ = _run(
        "列出当前工作区所有变更文件",
        [{"path": "src/a.py", "status": "modified"}],
        _selector_outcome({"evidence_id": "E1", "operation": "list_all"}),
        total=8,
        truncated=True,
    )
    assert result.status == "completed"
    assert "部分清单" in result.answer
    assert "truncated=true" in result.answer
    assert "不穷举" in result.answer


def test_commit_range_scope_is_rendered_from_the_executed_tool_call():
    result, _, _ = _run(
        "列出两个提交之间的变更文件",
        [{"path": "src/a.py", "status": "modified"}],
        _selector_outcome({"evidence_id": "E1", "operation": "list_all"}),
        tool_arguments={
            "mode": "commit_range",
            "base_ref": "abc123",
            "head_ref": "def456",
        },
    )
    assert result.status == "completed"
    assert "commit_range" in result.answer
    assert "abc123" in result.answer
    assert "def456" in result.answer
    assert "src/a.py" in result.answer


def test_wrong_but_well_formed_selector_never_claims_task_semantics(monkeypatch):
    # This fake response tests protocol behavior only. It does not demonstrate
    # that a model understood the user's request to list every change.
    import core.tool_agent.runtime as runtime_module

    original_finalize = runtime_module.finalize_changed_files_typed
    typed_results = []

    def capture_typed_result(*args, **kwargs):
        typed_result = original_finalize(*args, **kwargs)
        typed_results.append(typed_result)
        return typed_result

    monkeypatch.setattr(
        runtime_module, "finalize_changed_files_typed", capture_typed_result
    )
    result, provider, _ = _run(
        "列出当前工作区所有变更文件",
        [
            {"path": "src/deleted.py", "status": "deleted"},
            {"path": "src/modified.py", "status": "modified"},
        ],
        _selector_outcome(
            {"evidence_id": "E1", "operation": "filter_status", "status": "deleted"}
        ),
    )
    assert result.status == "completed"
    assert "deleted 状态项" in result.answer
    assert "src/deleted.py" in result.answer
    assert "src/modified.py" not in result.answer
    assert provider.selector_calls == 1
    assert typed_results[0].protocol_valid is True
    assert typed_results[0].accepted is True
    assert typed_results[0].user_task_coverage == "UNASSESSED_NO_SEMANTIC_REVIEW"
    # The Runtime produced a source-checked filtered delivery. This offline
    # fixture cannot mark it as satisfying the user's broader intent.


def test_wrong_evidence_id_fails_closed_and_does_not_reuse_draft_answer():
    result, provider, _ = _run(
        "列出当前工作区所有变更文件",
        [{"path": "src/a.py", "status": "modified"}],
        _selector_outcome({"evidence_id": "E99", "operation": "list_all"}),
    )
    assert result.status == "refused"
    assert result.answer is None
    assert provider.selector_calls == 1


def test_invalid_selector_json_fails_without_retry_or_text_fallback():
    bad_selector = selector_outcome_from_response("{broken", call_metadata=_metadata())
    assert bad_selector.status == "failed"
    assert bad_selector.failure_code == ACTION_PARSE_FAILED
    result, provider, _ = _run(
        "列出当前工作区所有变更文件",
        [{"path": "src/a.py", "status": "modified"}],
        bad_selector,
    )
    assert result.status == "failed"
    assert result.failure_code == ACTION_PARSE_FAILED
    assert provider.selector_calls == 1


def test_dev015_router_requirement_prevents_selector_path():
    query = "列出已删除的源码文件"
    requirement = route_engineering_evidence_requirement(query)
    assert requirement.requirement_profile.value == "PROJECT_CODE_V1"
    result, provider, _ = _run(
        query,
        [{"path": "src/deleted.py", "status": "deleted"}],
        _selector_outcome({"evidence_id": "E1", "operation": "filter_status", "status": "deleted"}),
    )
    assert result.status == "refused"
    assert result.answer is None
    assert provider.selector_calls == 0


def test_existing_natural_language_gate_keeps_open_analysis_on_legacy_path():
    query = "列出变更文件，并说明这些信息能否判断哪个最重要"
    natural_answer = "当前 working_tree 变更清单：\nsrc/a.py (已修改) [E1]"
    result, provider, _ = _run(
        query,
        [{"path": "src/a.py", "status": "modified"}],
        _selector_outcome({"response_type": "refusal", "reason_code": "unsupported_request"}),
        answer=natural_answer,
    )
    # The old binding accepts the bounded inventory/caveat, so selector is
    # not forced merely because changed_files ran. This is not a semantic
    # claim that the answer completed the open-ended importance analysis.
    assert result.status == "completed"
    assert result.answer == natural_answer
    assert provider.selector_calls == 0


def test_unsupported_selector_keeps_legacy_gate_and_does_not_emit_status_answer():
    result, provider, _ = _run(
        "为什么这个文件被删除？",
        [{"path": "src/deleted.py", "status": "deleted"}],
        _selector_outcome(
            {"response_type": "refusal", "reason_code": "unsupported_request"}
        ),
        answer="这个文件被删除是因为清理了旧实现。",
    )
    assert result.status == "refused"
    assert result.answer is None
    assert result.reason_code == "INSUFFICIENT_EVIDENCE_TO_FINALIZE"
    assert provider.selector_calls == 1


def test_ordinary_direct_answer_does_not_trigger_selector():
    provider = ScriptedTypedProvider(
        [FinalAnswerAction(action="final_answer", answer="RAG combines retrieval with generation.")]
    )
    runtime = ToolAgentRuntime(registry=ToolRegistry(), provider=provider)
    unified = build_full_unified_runtime(
        runtime,
        planner=NoRetrievalPlanner(),
        retrieval_port=EmptyRetrievalPort(),
    )
    result = unified.run("What does RAG mean?")
    assert result.status == "completed"
    assert result.answer == "RAG combines retrieval with generation."
    assert provider.selector_calls == 0


def test_failed_source_cannot_use_unreferenced_draft_as_trusted_empty_answer():
    class FailedHandler:
        def execute(self, arguments):
            raise RuntimeError("synthetic git failure")

    registry = ToolRegistry()
    registry.register(CHANGED_FILES_SPEC, FailedHandler())
    provider = ScriptedTypedProvider(
        [
            ToolCallAction(
                action="tool_call",
                tool_name="changed_files",
                arguments={"mode": "working_tree"},
            ),
            FinalAnswerAction(
                action="final_answer",
                answer="当前没有变更文件。",
            ),
        ]
    )
    runtime = ToolAgentRuntime(registry=registry, provider=provider)
    unified = build_full_unified_runtime(
        runtime,
        planner=NoRetrievalPlanner(),
        retrieval_port=EmptyRetrievalPort(),
    )
    result = unified.run("列出当前工作区所有变更文件")
    assert result.status == "refused"
    assert result.answer is None
    assert provider.selector_calls == 0


def test_source_identity_scope_and_observation_are_rechecked():
    result, provider, _ = _run(
        "列出当前工作区所有变更文件",
        [{"path": "src/a.py", "status": "modified"}],
        _selector_outcome({"evidence_id": "E1", "operation": "list_all"}),
    )
    assert result.status == "completed"
    execution = provider.selector_inputs[0][1]
    tampered = replace(
        execution,
        evidence=replace(execution.evidence, scope='{"mode":"commit_range","base_ref":"a","head_ref":"b"}'),
    )
    assert _validate_source(tampered, current_public_evidence=result.evidence) == "CURRENT_EVIDENCE_SET_MISMATCH"
    assert _validate_source(
        tampered, current_public_evidence=(tampered.evidence,)
    ) == "EVIDENCE_SOURCE_MISMATCH"


def test_open_unsupported_refusal_is_explicit_and_never_renders_typed_rows():
    outcome = selector_outcome_from_response(
        json.dumps({"response_type": "refusal", "reason_code": "unsupported_request"}),
        call_metadata=_metadata(),
    )
    assert outcome.status == "refusal"
    assert outcome.refusal_reason == "unsupported_request"


def test_malformed_refusal_reason_fails_closed_without_raising():
    outcome = selector_outcome_from_response(
        json.dumps({"response_type": "refusal", "reason_code": ["unsupported_request"]}),
        call_metadata=_metadata(),
    )
    assert outcome.status == "failed"
    assert outcome.failure_code == ACTION_PARSE_FAILED


def test_openai_compatible_provider_uses_one_fake_selector_request():
    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"evidence_id":"E1","operation":"list_all"}'
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=21, completion_tokens=8),
            )

    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = OpenAICompatibleAgentDecisionProvider(
        provider="fake",
        model="fake-model",
        api_key="test-only-not-a-secret",
        client=client,
    )
    _result, script, _ = _run(
        "列出当前工作区所有变更文件",
        [{"path": "src/a.py", "status": "modified"}],
        _selector_outcome({"evidence_id": "E1", "operation": "list_all"}),
    )
    execution = script.selector_inputs[0][1]
    outcome = provider.select_changed_files(
        "列出当前工作区所有变更文件",
        execution=execution,
        evidence_requirement=route_engineering_evidence_requirement("列出当前工作区所有变更文件"),
    )
    assert outcome.status == "selected"
    assert outcome.selector == {"evidence_id": "E1", "operation": "list_all"}
    assert outcome.call_metadata.model == "fake-model"
    assert outcome.call_metadata.input_tokens == 21
    assert len(completions.calls) == 1
    call = completions.calls[0]
    assert call["model"] == "fake-model"
    assert call["temperature"] == 0
    assert call["max_tokens"] == 128
    assert call["response_format"] == {"type": "json_object"}
    payload = json.loads(call["messages"][1]["content"])
    assert payload["user_request"] == "列出当前工作区所有变更文件"
    assert "gold" not in call["messages"][1]["content"].lower()
