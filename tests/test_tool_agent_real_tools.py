"""Tests for Gate 4 real read-only tools (G4-TOOLS-03).

Covers calculator (AST allowlist evaluator), knowledge_search (injected
Fake RetrievalPort), code_search (tmp_path real mini repo tree), and the
integration of all three through ToolRegistry + ToolExecutor. No LLM, no
real retrieval network, no Holdout, no Gate 3 modification.
"""

from __future__ import annotations

import pytest

from core.agent_runtime import Document
from core.tool_agent import (
    INVALID_TOOL_ARGUMENTS,
    TOOL_EXECUTION_FAILED,
    CalculatorHandler,
    CodeSearchHandler,
    KnowledgeSearchHandler,
    ToolCall,
    ToolExecutor,
    ToolRegistry,
    build_readonly_tool_registry,
)
from core.tool_agent.tools.calculator import (
    CALCULATOR_SPEC,
    CalculatorError,
    evaluate_expression,
)

# ---- Calculator 单元（evaluate_expression） ----


class TestCalculatorUnit:
    def test_priority(self):
        assert evaluate_expression("12 * (3 + 4)") == 84

    def test_parentheses(self):
        assert evaluate_expression("(1 + 2) * 3") == 9

    def test_unary_minus(self):
        assert evaluate_expression("-5") == -5
        assert evaluate_expression("-(3 + 2)") == -5

    def test_division(self):
        assert evaluate_expression("7 / 2") == 3.5
        assert evaluate_expression("7 // 2") == 3

    def test_integer_ops(self):
        assert evaluate_expression("10 % 3") == 1
        assert evaluate_expression("2 ** 10") == 1024

    @pytest.mark.parametrize("expr", [
        "abc",                  # 名字
        "len(x)",               # 函数调用
        "x.attr",               # 属性访问
        "'str'",                # 字符串
        '"str"',                # 字符串
        "True",                 # 布尔
        "1 + True",             # 布尔参与运算
        "[1, 2, 3]",            # 容器
        "{'a': 1}",             # dict
        "lambda: 1",            # lambda
        "a[0]",                 # 下标
    ])
    def test_forbidden_syntax(self, expr):
        with pytest.raises(CalculatorError):
            evaluate_expression(expr)

    def test_division_by_zero(self):
        with pytest.raises(CalculatorError, match="除以零"):
            evaluate_expression("1 / 0")
        with pytest.raises(CalculatorError):
            evaluate_expression("1 // 0")

    def test_oversized_exponent(self):
        with pytest.raises(CalculatorError, match="幂指数"):
            evaluate_expression("2 ** 999999")

    def test_infinity_rejected(self):
        with pytest.raises(CalculatorError, match="有限"):
            evaluate_expression("1e308 * 1e308")


# ---- Calculator 经 Executor ----


class TestCalculatorExecutor:
    def _executor(self):
        reg = ToolRegistry()
        reg.register(CALCULATOR_SPEC, CalculatorHandler())
        return ToolExecutor(reg)

    def test_success(self):
        executor = self._executor()
        obs = executor.execute(ToolCall.create("calculator", {"expression": "12 * (3 + 4)"}))
        assert obs.status == "ok"
        assert obs.result == {"value": 84}

    def test_extra_argument_rejected(self):
        executor = self._executor()
        obs = executor.execute(
            ToolCall.create("calculator", {"expression": "1+1", "extra": 1})
        )
        assert obs.error_code == INVALID_TOOL_ARGUMENTS

    def test_expression_too_long_rejected_by_schema(self):
        executor = self._executor()
        long_expr = "1" * 201
        obs = executor.execute(ToolCall.create("calculator", {"expression": long_expr}))
        assert obs.error_code == INVALID_TOOL_ARGUMENTS

    def test_arithmetic_error_is_structured(self):
        executor = self._executor()
        obs = executor.execute(ToolCall.create("calculator", {"expression": "1 / 0"}))
        assert obs.error_code == TOOL_EXECUTION_FAILED
        assert obs.result is None
        # 不得泄漏 traceback / 异常细节
        assert "ZeroDivisionError" not in str(obs.to_dict())
        assert "Traceback" not in str(obs.to_dict())


# ---- Fake RetrievalPort ----


class FakeRetrievalPort:
    def __init__(self, docs=(), strategies=("bm25", "hybrid")):
        self._docs = tuple(docs)
        self.supported_strategies = strategies
        self.calls = []

    def search(self, query, strategy, top_k):
        self.calls.append((query, strategy, top_k))
        return self._docs


def make_doc(
    content: str,
    source_name: str = "doc.md",
    chunk_id: str = "chunk-1",
    score: float = 1.0,
    rank: int = 1,
) -> Document:
    return Document(
        chunk_id=chunk_id,
        document_id="doc-1",
        source_name=source_name,
        content=content,
        score=score,
        rank=rank,
    )


# ---- knowledge_search ----


class TestKnowledgeSearch:
    def _executor(self, port, **kwargs):
        reg = ToolRegistry()
        from core.tool_agent.tools.knowledge_search import KNOWLEDGE_SEARCH_SPEC

        reg.register(KNOWLEDGE_SEARCH_SPEC, KnowledgeSearchHandler(port, **kwargs))
        return ToolExecutor(reg)

    def test_query_passed_and_mapping_correct(self):
        docs = (
            make_doc("RRF tie breaker 是确定性排序", source_name="docs/rrf.md",
                     chunk_id="c1", score=0.9, rank=1),
            make_doc("BM25 是 primary", source_name="docs/bm25.md",
                     chunk_id="c2", score=0.8, rank=2),
        )
        port = FakeRetrievalPort(docs=docs)
        executor = self._executor(port)
        obs = executor.execute(ToolCall.create("knowledge_search", {"query": "RRF tie breaker"}))
        assert obs.status == "ok"
        assert port.calls == [("RRF tie breaker", "bm25", 5)]
        m0, m1 = obs.result["matches"]
        assert m0 == {"rank": 1, "source_name": "docs/rrf.md", "chunk_id": "c1",
                      "score": 0.9, "snippet": "RRF tie breaker 是确定性排序"}
        assert m1["rank"] == 2

    def test_fixed_strategy_and_top_k(self):
        port = FakeRetrievalPort(docs=(make_doc("x"),))
        executor = self._executor(port, strategy="bm25", top_k=5)
        executor.execute(ToolCall.create("knowledge_search", {"query": "x"}))
        assert port.calls[0][1:] == ("bm25", 5)

    def test_model_cannot_override_strategy_or_top_k(self):
        port = FakeRetrievalPort(docs=(make_doc("x"),))
        executor = self._executor(port)
        for bad_args in ({"query": "x", "top_k": 100}, {"query": "x", "strategy": "hybrid"}):
            obs = executor.execute(ToolCall.create("knowledge_search", bad_args))
            assert obs.error_code == INVALID_TOOL_ARGUMENTS
        assert port.calls == []  # handler 0 calls

    def test_snippet_truncated(self):
        long_content = "A" * 700
        port = FakeRetrievalPort(docs=(make_doc(long_content),))
        executor = self._executor(port, snippet_limit=500)
        obs = executor.execute(ToolCall.create("knowledge_search", {"query": "A"}))
        assert len(obs.result["matches"][0]["snippet"]) == 500

    def test_empty_result(self):
        port = FakeRetrievalPort(docs=())
        executor = self._executor(port)
        obs = executor.execute(ToolCall.create("knowledge_search", {"query": "zzz"}))
        assert obs.status == "ok"
        assert obs.result == {"matches": []}

    def test_backend_exception(self):
        class BoomPort(FakeRetrievalPort):
            def search(self, query, strategy, top_k):
                raise RuntimeError("backend boom")

        executor = self._executor(BoomPort(docs=()))
        obs = executor.execute(ToolCall.create("knowledge_search", {"query": "x"}))
        assert obs.error_code == TOOL_EXECUTION_FAILED
        assert "backend boom" not in str(obs.to_dict())

    def test_unsupported_strategy(self):
        port = FakeRetrievalPort(docs=(), strategies=("hybrid",))
        executor = self._executor(port, strategy="bm25")
        obs = executor.execute(ToolCall.create("knowledge_search", {"query": "x"}))
        assert obs.error_code == TOOL_EXECUTION_FAILED
        assert port.calls == []  # 不偷偷换策略

    def test_handler_requires_retrieval_port(self):
        with pytest.raises(TypeError, match="RetrievalPort"):
            KnowledgeSearchHandler(retrieval_port="not-a-port")


# ---- code_search ----


def build_repo(tmp_path):
    """构造一个小型真实目录树，覆盖允许/排除/secret/大小写/嵌套。"""
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "foo.py").write_text(
        "class Alpha:\n    pass\n\ndef helper():\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "core" / "nested").mkdir()
    (tmp_path / "core" / "nested" / "mod.py").write_text(
        "# module\nPipelineRetrievalAdapter 定义在这\n",
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text(
        "# Guide\npipelineRetrievaladapter 是小写\n",
        encoding="utf-8",
    )
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "config.json").write_text(
        '{"key": "PipelineRetrievalAdapter"}\n',
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "other.txt").write_text(
        "PipelineRetrievalAdapter in txt\n",
        encoding="utf-8",
    )
    # 隐藏目录 / 排除目录（放在 core/ 下，真正命中 dirnames 过滤）
    (tmp_path / "core" / ".hidden").mkdir()
    (tmp_path / "core" / ".hidden" / "h.py").write_text(
        "PipelineRetrievalAdapter hidden\n", encoding="utf-8"
    )
    (tmp_path / "core" / "__pycache__").mkdir()
    (tmp_path / "core" / "__pycache__" / "c.py").write_text(
        "PipelineRetrievalAdapter pycache\n", encoding="utf-8"
    )
    (tmp_path / "core" / "experiments").mkdir()
    (tmp_path / "core" / "experiments" / "e.py").write_text(
        "PipelineRetrievalAdapter exp\n", encoding="utf-8"
    )
    (tmp_path / "core" / "venv").mkdir()
    (tmp_path / "core" / "venv" / "v.py").write_text(
        "PipelineRetrievalAdapter venv\n", encoding="utf-8"
    )
    # secret / 凭证文件（应被忽略）
    (tmp_path / "core" / ".env").write_text(
        "TOKEN=abc\nPipelineRetrievalAdapter\n", encoding="utf-8"
    )
    (tmp_path / "core" / "secret_token.py").write_text(
        "PipelineRetrievalAdapter secret\n", encoding="utf-8"
    )
    # 非允许后缀 / 不可读二进制
    (tmp_path / "core" / "data.bin").write_bytes(b"\x00\x01PipelineRetrievalAdapter")
    # 允许后缀但超大（>1MiB）→ 跳过
    (tmp_path / "core" / "big.py").write_text(
        "PipelineRetrievalAdapter\n" * (2 * 1024 * 1024), encoding="utf-8"
    )
    # repo 根但不在允许目录 → 不扫描
    (tmp_path / "root_notes.txt").write_text(
        "PipelineRetrievalAdapter outside allowed dirs\n", encoding="utf-8"
    )
    return tmp_path


class TestCodeSearch:
    def _executor(self, repo_root):
        reg = ToolRegistry()
        from core.tool_agent.tools.code_search import CODE_SEARCH_SPEC

        reg.register(CODE_SEARCH_SPEC, CodeSearchHandler(repo_root=repo_root))
        return ToolExecutor(reg)

    def test_finds_python_symbol_and_md_text(self, tmp_path):
        repo = build_repo(tmp_path)
        executor = self._executor(repo)
        obs = executor.execute(ToolCall.create("code_search", {"query": "helper"}))
        assert obs.status == "ok"
        assert obs.result["matches"][0]["path"] == "core/foo.py"

    def test_case_insensitive(self, tmp_path):
        repo = build_repo(tmp_path)
        executor = self._executor(repo)
        obs_low = executor.execute(
            ToolCall.create("code_search", {"query": "pipelineRetrievaladapter"})
        )
        obs_upper = executor.execute(
            ToolCall.create("code_search", {"query": "PIPELINERETRIEVALADAPTER"})
        )
        assert obs_low.status == "ok" and obs_upper.status == "ok"

    def test_deterministic_ordering_and_exclusions(self, tmp_path):
        repo = build_repo(tmp_path)
        executor = self._executor(repo)
        obs = executor.execute(ToolCall.create("code_search", {"query": "PipelineRetrievalAdapter"}))
        keys = [(m["path"], m["line"]) for m in obs.result["matches"]]
        assert keys == sorted(keys)
        paths = [m["path"] for m in obs.result["matches"]]
        for banned in (
            "__pycache__", "experiments/", "venv/", ".hidden", ".env",
            "secret_token", "data.bin", "big.py", "root_notes",
        ):
            assert not any(banned in p for p in paths), f"{banned} 不应出现在结果中"
        assert len(obs.result["matches"]) <= 10

    def test_max_matches_and_line_truncation(self, tmp_path):
        repo = tmp_path
        (repo / "core").mkdir()
        (repo / "core" / "m.py").write_text(
            "x = 1\n" + ("# " + "q" * 500 + "\n") * 20, encoding="utf-8"
        )
        executor = self._executor(repo)
        obs = executor.execute(ToolCall.create("code_search", {"query": "qqqqq"}))
        assert len(obs.result["matches"]) <= 10
        for m in obs.result["matches"]:
            assert len(m["text"]) <= 300

    def test_never_returns_absolute_path(self, tmp_path):
        repo = build_repo(tmp_path)
        executor = self._executor(repo)
        obs = executor.execute(ToolCall.create("code_search", {"query": "Alpha"}))
        assert obs.result["matches"]
        for m in obs.result["matches"]:
            assert not m["path"].startswith("/")
            assert ":" not in m["path"].split("/")[0]  # 无盘符
            assert str(repo) not in m["path"]

    def test_does_not_scan_outside_allowed_dirs(self, tmp_path):
        repo = build_repo(tmp_path)
        executor = self._executor(repo)
        obs = executor.execute(ToolCall.create("code_search", {"query": "root_notes"}))
        assert obs.result["matches"] == []

    def test_root_not_dir_fails_fast(self, tmp_path):
        with pytest.raises(ValueError, match="不是目录"):
            CodeSearchHandler(repo_root=tmp_path / "nope")

    def test_single_unreadable_file_skipped(self, tmp_path):
        repo = tmp_path
        (repo / "core").mkdir()
        (repo / "core" / "bad.py").write_bytes(
            b"\xff\xfe\x00\x81 broken utf-8 PipelineRetrievalAdapter"
        )
        (repo / "core" / "good.py").write_text(
            "class Good:  # PipelineRetrievalAdapter\n", encoding="utf-8"
        )
        executor = self._executor(repo)
        obs = executor.execute(ToolCall.create("code_search", {"query": "PipelineRetrievalAdapter"}))
        assert obs.status == "ok"
        assert [m["path"] for m in obs.result["matches"]] == ["core/good.py"]


# ---- Integration：三个真实 Tool 统一注册与执行 ----


class TestIntegration:
    def test_all_three_tools_via_default_factory(self, tmp_path):
        repo = build_repo(tmp_path)
        port = FakeRetrievalPort(
            docs=(make_doc("RRF 采用确定性 tie breaker", source_name="docs/rrf.md"),),
            strategies=("bm25",),
        )
        registry = build_readonly_tool_registry(repo_root=repo, retrieval_port=port)
        executor = ToolExecutor(registry)

        cases = [
            (ToolCall.create("calculator", {"expression": "2 * 21"}), {"value": 42}),
            (ToolCall.create("code_search", {"query": "helper"}), None),
            (ToolCall.create("knowledge_search", {"query": "RRF"}), None),
        ]
        for call, expected in cases:
            obs = executor.execute(call)
            assert obs.status == "ok", f"{call.tool_name}: {obs.error_code}"
            if expected is not None:
                assert obs.result == expected
        assert port.calls == [("RRF", "bm25", 5)]

    def test_all_three_go_through_registry(self, tmp_path):
        repo = build_repo(tmp_path)
        port = FakeRetrievalPort(docs=(), strategies=("bm25",))
        registry = build_readonly_tool_registry(repo_root=repo, retrieval_port=port)
        names = sorted(spec.name for spec in registry.list_specs())
        assert names == ["calculator", "code_search", "knowledge_search"]
