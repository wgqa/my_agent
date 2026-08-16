"""Tests for G4-EVAL-06B-01 Gate 4 formal Dev Runner harness.

0-LLM harness：Fake / Scripted Decision Provider + real Tool wiring + real corpus
preflight（语料缺失时 preflight 相关测试跳过）。覆盖：deterministic assertion 精确
语义、case score / 15 项冻结指标（含 zero denominator→null）、Runner preflight gates
（tracked dirty / dataset SHA / evaluation_set_id / corpus id-count / evidence /
code-gold diff / output no-overwrite / --execute 授权）、两阶段 Gold 隔离（execution
artifact 无 Gold-only 字段）、perfect scripted run 全指标、total decision calls ≤120。
无 real LLM / 无网络。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.tool_agent import (
    ACTION_PARSE_FAILED,
    AGENT_BUDGET_EXCEEDED,
    AGENT_DUPLICATE_TOOL_CALL,
    AgentDecisionOutcome,
    FinalAnswerAction,
    RefuseAction,
    ToolCallAction,
)
from evaluation.gate4 import (
    FROZEN_EVALUATION_SET_ID,
    KNOWLEDGE_CORPUS_FILE_COUNT,
    KNOWLEDGE_CORPUS_ID,
    CompletionAssertion,
    Gate4ToolUseEvaluationSet,
)
from evaluation.gate4.evaluator import (
    CaseScore,
    compute_metrics,
    evaluate_assertion,
    evaluate_case,
    executed_tool_sequence,
)
from evaluation.gate4.runner import (
    Gate4ToolUseRunner,
    RunnerAbort,
    sha256_bytes,
    verify_corpus_provenance,
    verify_dataset_identity,
    verify_knowledge_gold_provenance,
)
from evaluation.gate4.runner_models import (
    DecisionSummary,
    Gate4ExecutionResult,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "evaluation" / "gate4" / "data"
JSONL = DATA_DIR / "tool_use_dev_v1.jsonl"
MANIFEST = DATA_DIR / "tool_use_dev_manifest_v1.json"

GOLD_ONLY_FIELDS = {
    "category",
    "expected_terminal",
    "expected_first_action",
    "expected_first_tool",
    "expected_first_tools",
    "required_tools",
    "allowed_tool_sequences",
    "forbidden_tools",
    "completion_assertions",
    "allowed_refuse_reason_codes",
    "knowledge_gold",
    "rationale",
    "tags",
}


def _real_set() -> Gate4ToolUseEvaluationSet:
    return Gate4ToolUseEvaluationSet.load_jsonl(JSONL)


def _result(
    status: str,
    answer: str | None = None,
    reason_code: str | None = None,
    failure_code: str | None = None,
    *,
    iterations: int = 1,
    tool_calls: int = 0,
    tool_errors: int = 0,
    trace: tuple[dict, ...] = (),
    decisions: tuple[DecisionSummary, ...] = (),
) -> Gate4ExecutionResult:
    return Gate4ExecutionResult(
        case_id="x",
        status=status,
        answer=answer,
        reason_code=reason_code,
        failure_code=failure_code,
        iterations_used=iterations,
        tool_calls_used=tool_calls,
        tool_errors_used=tool_errors,
        trace=trace,
        decisions=decisions,
        decision_call_count=len(decisions),
        input_tokens=None,
        output_tokens=None,
        total_latency_ms=0.0,
        prompt_version=None,
        prompt_sha256=None,
        toolset_sha256=None,
    )


def _assertion(a_type: str, value) -> CompletionAssertion:
    return CompletionAssertion(type=a_type, value=value)


class FakeGitContext:
    def __init__(self, *, tracked_clean=True, code_gold_diff_ok=True,
                 source_commit="c4893728912e2e5245c909225706abc2aa8ac980"):
        self._clean = tracked_clean
        self._diff_ok = code_gold_diff_ok
        self._commit = source_commit

    def source_commit(self) -> str:
        return self._commit

    def is_tracked_clean(self) -> bool:
        return self._clean

    def code_gold_diff_ok(self, ref: str) -> bool:
        return self._diff_ok


class FakeRetrievalPort:
    supported_strategies = ("bm25",)

    def search(self, query, strategy, top_k):
        return ()


def _stub_corpus_verifier(corpus_root, set_obj):
    return (KNOWLEDGE_CORPUS_ID, KNOWLEDGE_CORPUS_FILE_COUNT,
            ("rag/检索与生成.md",))


def _outcome(action, failure_code=None):
    return AgentDecisionOutcome(
        action=action, failure_code=failure_code, call_metadata=None
    )


# ---------------------------------------------------------------------- #
# Perfect scripted provider（用数据集 Gold 构造一个"完美 Agent"驱动状态机）
# ---------------------------------------------------------------------- #


_CODE_SEARCH_PAYLOAD = {
    "g4q009": ("ToolAgentRuntime", "core/tool_agent/runtime.py"),
    "g4q010": ("PipelineRetrievalAdapter", "core/agent_runtime/adapters.py"),
    "g4q011": ("compute_toolset_sha256", "core/tool_agent/decision_prompt.py"),
    "g4q012": ("merge_subquery_results", "core/agent_runtime/evidence.py"),
}


def _assertion_answer(case) -> str:
    for a in case.completion_assertions:
        if a.type == "answer_number_equals":
            return str(a.value)
        if a.type == "answer_contains":
            return a.value
        if a.type == "answer_contains_all":
            return ",".join(a.value)
        if a.type == "path_contains":
            return a.value
        if a.type == "answer_nonempty":
            return "好的"
    raise ValueError(f"{case.case_id} 无可用 assertion")


def _case_script(case):
    cid = case.case_id
    if case.category == "direct_answer":
        return [_outcome(FinalAnswerAction("final_answer", _assertion_answer(case)))]
    if case.category == "calculator":
        value = _assertion_answer(case)
        return [
            _outcome(ToolCallAction(action="tool_call", tool_name="calculator", arguments={"expression":value})),
            _outcome(FinalAnswerAction("final_answer", value)),
        ]
    if case.category == "code_search":
        query, path = _CODE_SEARCH_PAYLOAD[cid]
        return [
            _outcome(ToolCallAction(action="tool_call", tool_name="code_search", arguments={"query":query})),
            _outcome(FinalAnswerAction("final_answer", path)),
        ]
    if case.category == "knowledge_search":
        return [
            _outcome(
                ToolCallAction(action="tool_call", tool_name="knowledge_search", arguments={"query":cid})
            ),
            _outcome(FinalAnswerAction("final_answer", _assertion_answer(case))),
        ]
    if case.category == "multi_step":
        return _multi_step_script(case)
    if case.category == "refusal_safety":
        code = case.allowed_refuse_reason_codes[0]
        return [_outcome(RefuseAction("refuse", code))]
    raise ValueError(f"未知 category {case.category!r}")


def _multi_step_script(case):
    cid = case.case_id
    scripts = {
        "g4q017": [
            ToolCallAction(action="tool_call", tool_name="code_search", arguments={"query":"MAX_INTEGER_BITS"}),
            ToolCallAction(action="tool_call", tool_name="calculator", arguments={"expression":"4096 * 2"}),
            FinalAnswerAction("final_answer", "8192"),
        ],
        "g4q018": [
            ToolCallAction(action="tool_call", tool_name="code_search", arguments={"query":"max_tool_calls"}),
            ToolCallAction(action="tool_call", tool_name="calculator", arguments={"expression":"4 * 3"}),
            FinalAnswerAction("final_answer", "12"),
        ],
        "g4q019": [
            ToolCallAction(action="tool_call", tool_name="knowledge_search", arguments={"query":"Float32"}),
            ToolCallAction(action="tool_call", tool_name="calculator", arguments={"expression":"4 * 128"}),
            FinalAnswerAction("final_answer", "512"),
        ],
        "g4q020": [
            ToolCallAction(action="tool_call", tool_name="knowledge_search", arguments={"query":"RRF k"}),
            ToolCallAction(
                action="tool_call", tool_name="code_search",
                arguments={"query": "merge_subquery_results_rrf"},
            ),
            FinalAnswerAction("final_answer", "merge_rrf_k 必须是有限正数"),
        ],
    }
    return [_outcome(a) for a in scripts[cid]]


class PerfectProvider:
    def __init__(self, script_by_query):
        self._scripts = script_by_query
        self.calls = 0

    def decide(self, registry, user_query, *, context=()):
        self.calls += 1
        script = self._scripts[user_query]
        step = len(context)
        if step >= len(script):
            return _outcome(FinalAnswerAction("final_answer", "done"))
        return script[step]


def _perfect_scripts(set_obj):
    return {case.query: _case_script(case) for case in set_obj.cases}


def _perfect_provider_factory(scripts):
    def factory(registry):
        return PerfectProvider(scripts)
    return factory


def _make_runner(
    tmp_path,
    *,
    mode="preflight",
    authorized=True,
    git=None,
    verifier=None,
    provider_factory=None,
    dataset=JSONL,
):
    return Gate4ToolUseRunner(
        repo_root=REPO_ROOT,
        dataset_path=dataset,
        manifest_path=MANIFEST,
        output_root=tmp_path / "out",
        corpus_root=tmp_path / "corpus",
        mode=mode,
        execution_authorized=authorized,
        git_context=git or FakeGitContext(),
        corpus_verifier=verifier or _stub_corpus_verifier,
        retrieval_port=FakeRetrievalPort(),
        provider_factory=provider_factory,
        provider="fake",
        model="fake",
    )


# ---------------------------------------------------------------------- #
# Deterministic assertions（protocol §16 精确语义）
# ---------------------------------------------------------------------- #


class TestAssertions:
    def test_answer_nonempty(self):
        assert evaluate_assertion(_assertion("answer_nonempty", True),
                                  _result("completed", "ok"))
        assert not evaluate_assertion(_assertion("answer_nonempty", True),
                                      _result("completed", "  "))
        assert not evaluate_assertion(_assertion("answer_nonempty", True),
                                      _result("refused"))

    def test_answer_contains_unicode(self):
        assert evaluate_assertion(_assertion("answer_contains", "排名"),
                                  _result("completed", "RRF 基于排名"))
        assert not evaluate_assertion(_assertion("answer_contains", "排名"),
                                      _result("completed", "RRF 基于分数"))

    def test_answer_contains_all(self):
        assert evaluate_assertion(
            _assertion("answer_contains_all", ["300", "600"]),
            _result("completed", "300~600 tokens"),
        )
        assert not evaluate_assertion(
            _assertion("answer_contains_all", ["300", "600"]),
            _result("completed", "300 tokens"),
        )

    def test_number_equals_84_not_matching_184(self):
        # 绝不允许 str(expected) in answer（84 会误命中 184）
        assert evaluate_assertion(_assertion("answer_number_equals", 84),
                                  _result("completed", "结果是 84"))
        assert not evaluate_assertion(_assertion("answer_number_equals", 84),
                                      _result("completed", "结果是 184"))

    def test_number_equals_8_0_eq_8(self):
        assert evaluate_assertion(_assertion("answer_number_equals", 8),
                                  _result("completed", "答案是 8.0"))
        assert not evaluate_assertion(_assertion("answer_number_equals", 8),
                                      _result("completed", "答案是 0.8"))

    def test_number_equals_negative(self):
        assert evaluate_assertion(_assertion("answer_number_equals", -7),
                                  _result("completed", "-15 + 8 = -7"))
        assert not evaluate_assertion(_assertion("answer_number_equals", -7),
                                      _result("completed", "答案是 7"))

    def test_number_equals_large(self):
        assert evaluate_assertion(_assertion("answer_number_equals", 8192),
                                  _result("completed", "MAX_INTEGER_BITS 两倍是 8192"))

    def test_path_contains_normalizes_backslash(self):
        assert evaluate_assertion(
            _assertion("path_contains", "core/tool_agent/runtime.py"),
            _result("completed", "定义在 core\\tool_agent\\runtime.py"),
        )

    def test_status_equals_strict(self):
        assert evaluate_assertion(_assertion("status_equals", "refused"),
                                  _result("refused"))
        assert not evaluate_assertion(_assertion("status_equals", "refused"),
                                      _result("completed", "ok"))


# ---------------------------------------------------------------------- #
# Evaluator（case score / executed sequence / 指标）
# ---------------------------------------------------------------------- #


class TestEvaluator:
    def test_executed_sequence_uses_tool_observation_only(self):
        # duplicate-guard 拦截的调用不发射 tool_observation → 不进 executed sequence
        res = _result(
            "refused",
            reason_code=AGENT_DUPLICATE_TOOL_CALL,
            trace=(
                {"event_type": "tool_call_created", "tool_name": "calculator"},
                {"event_type": "tool_observation", "tool_name": "calculator"},
                {"event_type": "runtime_stopped", "error_code": AGENT_DUPLICATE_TOOL_CALL},
            ),
        )
        assert executed_tool_sequence(res) == ("calculator",)

    def test_micro_coverage_same_tool_three_times(self):
        # 同一 required Tool 调 3 次仍只覆盖 1 个 obligation
        set_obj = _real_set()
        case = next(c for c in set_obj.cases if c.case_id == "g4q005")  # calculator
        res = _result(
            "completed",
            answer="84",
            tool_calls=3,
            trace=(
                {"event_type": "tool_observation", "tool_name": "calculator"},
                {"event_type": "tool_observation", "tool_name": "calculator"},
                {"event_type": "tool_observation", "tool_name": "calculator"},
            ),
            decisions=(DecisionSummary(1, "tool_call", "calculator", None, None),),
        )
        score = evaluate_case(case, res)
        assert score.required_tools_hit == 1
        assert score.required_tools_total == 1

    def test_forbidden_tool_detected(self):
        set_obj = _real_set()
        case = next(c for c in set_obj.cases if c.case_id == "g4q009")  # code_search
        res = _result(
            "completed",
            answer="core/tool_agent/runtime.py",
            tool_calls=1,
            trace=(
                {"event_type": "tool_observation", "tool_name": "calculator"},
            ),
        )
        score = evaluate_case(case, res)
        assert score.forbidden_tool_used is True

    def test_zero_denominator_metrics_are_null(self):
        # 0 ToolCall → tool_error_rate / unnecessary_tool_call_rate value=null
        set_obj = _real_set()
        scores = [evaluate_case(c, _result("refused", reason_code="UNSAFE_REQUEST"))
                  for c in set_obj.cases if c.category == "refusal_safety"]
        metrics = compute_metrics(scores)
        assert metrics["tool_error_rate"] == {
            "numerator": 0, "denominator": 0, "value": None
        }
        assert metrics["unnecessary_tool_call_rate"] == {
            "numerator": 0, "denominator": 0, "value": None
        }

    def test_first_tool_accuracy_denominator_excludes_non_tool_call(self):
        # 分母只含 expected_first_action == tool_call 的 case
        set_obj = _real_set()
        scores = [
            evaluate_case(c, _result("completed", answer="ok"))
            for c in set_obj.cases
            if c.category == "direct_answer"
        ]
        metrics = compute_metrics(scores)
        assert metrics["first_tool_accuracy"]["denominator"] == 0
        assert metrics["first_tool_accuracy"]["value"] is None

    def test_allowed_sequence_match_rate_uses_multi_step_denominator(self):
        set_obj = _real_set()
        scores = [evaluate_case(c, _result("completed", answer="x"))
                  for c in set_obj.cases if c.category == "multi_step"]
        metrics = compute_metrics(scores)
        assert metrics["allowed_sequence_match_rate"]["denominator"] == 4

    def test_parse_failure_and_budget_stop_metrics(self):
        set_obj = _real_set()
        scores = []
        for i, c in enumerate(set_obj.cases):
            if i == 0:
                res = _result("failed", failure_code=ACTION_PARSE_FAILED)
            elif i == 1:
                res = _result("refused", reason_code=AGENT_BUDGET_EXCEEDED)
            else:
                res = _result("completed", answer="ok")
            scores.append(evaluate_case(c, res))
        metrics = compute_metrics(scores)
        assert metrics["parse_failure_rate"]["numerator"] == 1
        assert metrics["budget_stop_rate"]["numerator"] == 1

    def test_refuse_incorrect_reason_not_termination_correct(self):
        # g4q023 只允许 UNSUPPORTED_REQUEST；reason=UNSAFE_REQUEST → termination 错
        set_obj = _real_set()
        case = next(c for c in set_obj.cases if c.case_id == "g4q023")
        res = _result("refused", reason_code="UNSAFE_REQUEST")
        score = evaluate_case(case, res)
        assert score.terminal_correct is True
        assert score.termination_correct is False
        assert score.assertions_passed is True  # status_equals refused 通过

    def test_unnecessary_tool_count_metric(self):
        # 合成 CaseScore：非必需且非 forbidden 的调用被独立度量
        s = CaseScore(
            case_id="x", category="calculator", expected_terminal="completed",
            expected_first_action="tool_call", expected_first_tool="calculator",
            expected_first_tools=(), required_tools=("calculator",),
            forbidden_tools=(), allowed_tool_sequences=(),
            actual_first_action="tool_call", actual_first_tool="calculator",
            executed_tool_sequence=("calculator", "code_search"),
            required_tools_hit=1, required_tools_total=1,
            forbidden_tool_used=False, unnecessary_tool_call_count=1,
            assertions_passed=True, terminal_correct=True,
            termination_correct=True, allowed_sequence_match=None,
            status="completed", reason_code=None, failure_code=None,
            iterations=2, tool_calls=2, tool_errors=0,
        )
        metrics = compute_metrics([s])
        assert metrics["unnecessary_tool_call_rate"] == {
            "numerator": 1, "denominator": 2, "value": 0.5
        }


# ---------------------------------------------------------------------- #
# Runner preflight gates
# ---------------------------------------------------------------------- #


class TestPreflightGates:
    def test_preflight_pass(self, tmp_path):
        runner = _make_runner(tmp_path)
        facts = runner.run()
        assert facts["preflight"] == "PASS"
        assert facts["model_calls"] == 0
        assert facts["evaluation_set_id"] == FROZEN_EVALUATION_SET_ID
        assert facts["corpus_id"] == KNOWLEDGE_CORPUS_ID
        assert facts["corpus_file_count"] == KNOWLEDGE_CORPUS_FILE_COUNT

    def test_tracked_dirty_rejects_zero_calls(self, tmp_path):
        called = []
        runner = _make_runner(
            tmp_path,
            git=FakeGitContext(tracked_clean=False),
            provider_factory=lambda reg: called.append(1) or PerfectProvider({}),
        )
        with pytest.raises(RunnerAbort, match="tracked"):
            runner.run()
        assert called == []

    def test_execute_requires_auth_env(self, tmp_path):
        runner = _make_runner(tmp_path, mode="execute", authorized=False)
        with pytest.raises(RunnerAbort, match="EXECUTION_AUTHORIZED"):
            runner.run()

    def test_output_dir_exists_rejects(self, tmp_path):
        runner = _make_runner(tmp_path, mode="execute", authorized=True)
        facts = runner.preflight()
        run_dir = tmp_path / "out" / facts["run_id"]
        run_dir.mkdir(parents=True)
        with pytest.raises(FileExistsError):
            runner.run()

    def test_dataset_sha_mismatch_rejects(self, tmp_path):
        bad = tmp_path / "bad.jsonl"
        bad.write_text(JSONL.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        runner = _make_runner(tmp_path, dataset=bad)
        with pytest.raises(RunnerAbort, match="jsonl_sha256"):
            runner.run()

    def test_evaluation_set_id_mismatch_rejects(self, monkeypatch):
        set_obj = _real_set()
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        from evaluation.gate4 import runner as runner_mod

        monkeypatch.setattr(runner_mod, "FROZEN_EVALUATION_SET_ID", "000000000000")
        with pytest.raises(RunnerAbort, match="evaluation_set_id"):
            verify_dataset_identity(set_obj, sha256_bytes(JSONL.read_bytes()), manifest)

    def test_code_gold_diff_rejects(self, tmp_path):
        runner = _make_runner(tmp_path, git=FakeGitContext(code_gold_diff_ok=False))
        with pytest.raises(RunnerAbort, match="code Gold"):
            runner.run()

    def test_corpus_wrong_id_rejects(self, tmp_path):
        corpus = tmp_path / "corpus"
        (corpus / "a.md").parent.mkdir(parents=True, exist_ok=True)
        (corpus / "a.md").write_text("# a\n", encoding="utf-8")
        (corpus / "b.md").write_text("# b\n", encoding="utf-8")
        with pytest.raises(RunnerAbort, match="corpus_id"):
            verify_corpus_provenance(corpus, _real_set())

    def test_evidence_mismatch_rejects(self, tmp_path):
        # 构造含 source 文件但 evidence 不对的 corpus，验证 evidence substring 门
        set_obj = _real_set()
        corpus = tmp_path / "corpus"
        for case in set_obj.cases:
            if case.knowledge_gold is None:
                continue
            src = corpus / case.knowledge_gold.source_name
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text("这里没有证据短语", encoding="utf-8")
        with pytest.raises(RunnerAbort, match="evidence_phrase"):
            verify_knowledge_gold_provenance(corpus, set_obj)

    def test_evidence_ok_passes(self, tmp_path):
        set_obj = _real_set()
        corpus = tmp_path / "corpus"
        by_source: dict[str, set[str]] = {}
        for case in set_obj.cases:
            if case.knowledge_gold is None:
                continue
            by_source.setdefault(
                case.knowledge_gold.source_name, set()
            ).add(case.knowledge_gold.evidence_phrase)
        for source_name, phrases in by_source.items():
            src = corpus / source_name
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text(
                "\n".join("前置 " + p + " 后置" for p in phrases),
                encoding="utf-8",
            )
        verify_knowledge_gold_provenance(corpus, set_obj)  # 不应抛异常


# ---------------------------------------------------------------------- #
# 全流程（perfect scripted run）
# ---------------------------------------------------------------------- #


class TestFullPipeline:
    def _perfect_run(self, tmp_path):
        set_obj = _real_set()
        runner = _make_runner(
            tmp_path,
            mode="execute",
            authorized=True,
            provider_factory=_perfect_provider_factory(_perfect_scripts(set_obj)),
        )
        result = runner.run()
        return runner, result

    def test_perfect_scripted_run_all_accuracy_1(self, tmp_path):
        runner, result = self._perfect_run(tmp_path)
        m = result["metrics"]
        assert m["first_action_accuracy"]["value"] == 1.0
        assert m["first_tool_accuracy"]["value"] == 1.0
        assert m["required_tool_coverage"]["value"] == 1.0
        assert m["task_completion_rate"]["value"] == 1.0
        assert m["final_answer_correct_rate"]["value"] == 1.0
        assert m["termination_accuracy"]["value"] == 1.0
        assert m["allowed_sequence_match_rate"]["value"] == 1.0
        assert m["forbidden_tool_call_rate"]["value"] == 0.0
        assert m["duplicate_tool_call_rate"]["value"] == 0.0
        assert m["parse_failure_rate"]["value"] == 0.0
        assert m["budget_stop_rate"]["value"] == 0.0

    def test_artifacts_written_and_atomic_finalize(self, tmp_path):
        runner, result = self._perfect_run(tmp_path)
        final_dir = tmp_path / "out" / result["run_id"]
        assert final_dir.is_dir()
        assert not (tmp_path / "out" / f"{result['run_id']}.partial").exists()
        for name in ("run_config.json", "execution_results.jsonl",
                     "case_scores.jsonl", "metrics.json", "result.json",
                     "report.md", "artifact_manifest.json"):
            assert (final_dir / name).is_file(), name
        am = json.loads((final_dir / "artifact_manifest.json").read_text("utf-8"))
        assert am["run_id"] == result["run_id"]
        assert am["files"]["execution_results.jsonl"]["sha256"]
        assert am["files"]["execution_results.jsonl"]["size_bytes"] > 0

    def test_total_decision_calls_leq_120(self, tmp_path):
        runner, result = self._perfect_run(tmp_path)
        assert result["decision_call_count"] <= 120

    def test_execution_results_jsonl_gold_free(self, tmp_path):
        runner, result = self._perfect_run(tmp_path)
        final_dir = tmp_path / "out" / result["run_id"]
        lines = (final_dir / "execution_results.jsonl").read_text("utf-8").splitlines()
        assert len(lines) == 24
        for line in lines:
            rec = json.loads(line)
            assert not (set(rec.keys()) & GOLD_ONLY_FIELDS), rec.keys()
            serialized = json.dumps(rec, ensure_ascii=False)
            assert "api_key" not in serialized
            assert "Authorization" not in serialized
            assert "reasoning_content" not in serialized
            for d in rec["decisions"]:
                assert set(d.keys()) <= {
                    "iteration", "action_type", "tool_name",
                    "failure_code", "call_metadata",
                }
            prov = rec["provider"]
            if prov.get("prompt_sha256"):
                assert len(prov["prompt_sha256"]) == 64
            if prov.get("toolset_sha256"):
                assert len(prov["toolset_sha256"]) == 64

    def test_case_id_set_matches_gold(self, tmp_path):
        runner, result = self._perfect_run(tmp_path)
        final_dir = tmp_path / "out" / result["run_id"]
        exec_ids = {
            json.loads(line)["case_id"]
            for line in (final_dir / "execution_results.jsonl")
            .read_text("utf-8").splitlines()
        }
        assert exec_ids == {c.case_id for c in _real_set().cases}
        assert len(exec_ids) == 24

    def test_multi_step_both_legal_orders(self, tmp_path):
        # g4q020 两种合法顺序都允许：knowledge→code 与 code→knowledge
        set_obj = _real_set()
        base = _perfect_scripts(set_obj)
        q20 = next(c for c in set_obj.cases if c.case_id == "g4q020")
        script = base[q20.query]
        executed = tuple(
            s.action.tool_name for s in script
            if isinstance(s.action, ToolCallAction)
        )
        assert executed in (
            ("knowledge_search", "code_search"),
            ("code_search", "knowledge_search"),
        )
        assert list(executed) in [list(seq) for seq in q20.allowed_tool_sequences]
