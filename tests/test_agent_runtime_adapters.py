"""Tests for G3-RUNTIME-05B adapters and factory.

Covers: HybridRetriever.retrieve_sparse (BM25-only), PipelineRetrievalAdapter
mapping/fail-fast, PipelineAnswerAdapter grounded citation validation + error
strings, direct single-call + response defects, runtime hardening for illegal
port returns, and build_pipeline_agent_runtime. Uses only fakes and an
in-memory BM25 index; no network, no model calls, no Holdout.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.agent_runtime import (
    AgentRuntime,
    Document as RuntimeDocument,
    EvidenceBundle,
    GenerationAdapterError,
    PipelineAnswerAdapter,
    PipelineRetrievalAdapter,
    UnsupportedRetrievalStrategyError,
    build_pipeline_agent_runtime,
)
from core.loader.base import Document as LoaderDocument
from core.query_planning import (
    BaseQueryPlanner,
    PlannerOutcome,
    QueryPlan,
)
from core.retriever.bm25_only import BM25OnlyRetriever
from core.retriever.hybrid import HybridRetriever


# ---------------------------------------------------------------------------
# fakes / helpers
# ---------------------------------------------------------------------------


def _rdoc(
    chunk_id,
    source_name: str,
    content: str,
    rank: int,
    document_id=None,
    score=0.5,
) -> RuntimeDocument:
    return RuntimeDocument(
        chunk_id=chunk_id,
        document_id=document_id,
        source_name=source_name,
        content=content,
        score=score,
        rank=rank,
    )


def _single_outcome(original: str = "q") -> PlannerOutcome:
    plan = QueryPlan.create(
        original_query=original,
        query_type="fact",
        retrieval_required=True,
        action="single_retrieval",
        reason_code="SIMPLE_FACT",
        subqueries=(),
    )
    return PlannerOutcome(plan=plan, fallback_used=False, failure_code=None)


class _FakeEmbedding:
    def embed_query(self, query):
        raise AssertionError("retrieve_sparse 不应调用 Embedding")


class _FakeVectorStore:
    def search(self, *args, **kwargs):
        raise AssertionError("retrieve_sparse 不应调用 Dense Search")


class _StubBM25Only(BM25OnlyRetriever):
    """包装自定义 loader.Document 列表的假 BM25OnlyRetriever。"""

    def __init__(self, docs):
        super().__init__()
        self._docs = list(docs)

    def retrieve(self, query, top_k=5):
        return list(self._docs)


class _FakeResp:
    def __init__(self, content):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]


class _FakeDirectClient:
    def __init__(self, response=None, error=None, sink=None):
        self._response = response
        self._error = error
        self.sink = sink if sink is not None else []
        self.calls = 0

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls += 1
        self.sink.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _FakeGenerator:
    def __init__(self, answer, sink=None):
        self._answer = answer
        self.sink = sink if sink is not None else []
        self.calls = 0

    def generate(self, question, blocks):
        self.calls += 1
        self.last_question = question
        self.last_blocks = list(blocks)
        self.sink.extend(blocks)
        return self._answer


class _FakePlannerClient:
    def __init__(self, content, sink=None):
        self._content = content
        self.sink = sink if sink is not None else []
        self.calls = 0

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls += 1
        self.sink.append(kwargs)
        return _FakeResp(self._content)


_SINGLE_PLAN_JSON = json.dumps(
    {
        "query_type": "fact",
        "retrieval_required": True,
        "action": "single_retrieval",
        "reason_code": "SIMPLE_FACT",
        "subqueries": [],
    },
    ensure_ascii=False,
)
_DECOMPOSED_PLAN_JSON = json.dumps(
    {
        "query_type": "comparison",
        "retrieval_required": True,
        "action": "decomposed_retrieval",
        "reason_code": "COMPARISON_EVIDENCE",
        "subqueries": [
            {"id": "sq1", "query": "甲", "evidence_target": "t", "required": True},
            {"id": "sq2", "query": "乙", "evidence_target": "t", "required": True},
        ],
    },
    ensure_ascii=False,
)


def _bm25_retriever() -> BM25OnlyRetriever:
    retriever = BM25OnlyRetriever()
    retriever.build_sparse_index(
        [
            ("c1", "alpha beta", {"document_id": "d1", "source_name": "a.md"}),
            ("c2", "gamma delta", {"document_id": "d2", "source_name": "b.md"}),
        ]
    )
    return retriever


# ---------------------------------------------------------------------------
# 1. Hybrid retrieve_sparse：只跑 BM25
# ---------------------------------------------------------------------------


class TestRetrieveSparse:
    def test_hybrid_retrieve_sparse_no_dense_no_embedding(self):
        hybrid = HybridRetriever(
            embedding=_FakeEmbedding(), vector_store=_FakeVectorStore()
        )
        hybrid.build_sparse_index(
            [
                ("c1", "alpha beta", {"document_id": "d1", "source_name": "a.md"}),
                ("c2", "gamma delta", {"document_id": "d2", "source_name": "b.md"}),
            ]
        )
        docs = hybrid.retrieve_sparse("alpha", top_k=5)
        assert len(docs) == 1
        assert docs[0].metadata["id"] == "c1"
        assert docs[0].metadata["sparse_score"] > 0
        assert docs[0].metadata["source_name"] == "a.md"

    def test_hybrid_retrieve_sparse_rank_bm25_order(self):
        hybrid = HybridRetriever(
            embedding=_FakeEmbedding(), vector_store=_FakeVectorStore()
        )
        hybrid.build_sparse_index(
            [
                ("c1", "alpha beta", {"source_name": "a.md"}),
                ("c2", "alpha gamma alpha", {"source_name": "b.md"}),
            ]
        )
        # c2 命中 "alpha" 两次，BM25 分数应更高 → 排第一
        docs = hybrid.retrieve_sparse("alpha", top_k=5)
        assert docs[0].metadata["id"] == "c2"
        assert docs[1].metadata["id"] == "c1"


# ---------------------------------------------------------------------------
# 2/3/4. PipelineRetrievalAdapter 映射
# ---------------------------------------------------------------------------


class TestRetrievalAdapter:
    def test_adapter_maps_bm25_metadata(self):
        adapter = PipelineRetrievalAdapter(_bm25_retriever())
        docs = adapter.search("alpha", strategy="bm25", top_k=5)
        assert len(docs) == 1
        doc = docs[0]
        assert doc.chunk_id == "c1"
        assert doc.document_id == "d1"
        assert doc.source_name == "a.md"
        assert isinstance(doc.score, float)
        assert doc.rank == 1
        assert doc.content == "alpha beta"

    def test_adapter_source_fallback_to_source_key(self):
        retriever = _StubBM25Only(
            [
                LoaderDocument(
                    content="x", metadata={"id": "c1", "source": "fallback.md"}
                )
            ]
        )
        adapter = PipelineRetrievalAdapter(retriever)
        doc = adapter.search("q", strategy="bm25", top_k=5)[0]
        assert doc.source_name == "fallback.md"

    def test_adapter_missing_fields_stay_none(self):
        retriever = _StubBM25Only(
            [LoaderDocument(content="x", metadata={"id": "c1", "source_name": "a.md"})]
        )
        adapter = PipelineRetrievalAdapter(retriever)
        doc = adapter.search("q", strategy="bm25", top_k=5)[0]
        assert doc.chunk_id == "c1"
        assert doc.document_id is None
        assert doc.score is None
        assert doc.source_name == "a.md"
        assert doc.rank == 1

    def test_adapter_missing_source_name_fails_fast(self):
        retriever = _StubBM25Only(
            [LoaderDocument(content="x", metadata={"id": "c1"})]
        )
        adapter = PipelineRetrievalAdapter(retriever)
        with pytest.raises(ValueError):
            adapter.search("q", strategy="bm25", top_k=5)

    def test_adapter_unsupported_retriever(self):
        adapter = PipelineRetrievalAdapter(object())
        with pytest.raises(UnsupportedRetrievalStrategyError):
            adapter.search("q", strategy="bm25", top_k=5)

    def test_adapter_rejects_non_bm25_strategy(self):
        adapter = PipelineRetrievalAdapter(_bm25_retriever())
        with pytest.raises(UnsupportedRetrievalStrategyError):
            adapter.search("q", strategy="hybrid", top_k=5)


# ---------------------------------------------------------------------------
# 5/6/7/8. PipelineAnswerAdapter grounded
# ---------------------------------------------------------------------------


def _one_item_bundle() -> EvidenceBundle:
    return EvidenceBundle.from_documents(
        [_rdoc("c1", "a.md", "内容1", rank=1, document_id="d1", score=0.9)],
        query_id="q",
        max_items=5,
    )


class TestAnswerGrounded:
    def test_grounded_builds_context_blocks(self):
        bundle = _one_item_bundle()
        sink = []
        gen = _FakeGenerator("答案 [C1]", sink)
        adapter = PipelineAnswerAdapter(
            gen, direct_client=_FakeDirectClient(), direct_model="m"
        )
        answer = adapter.answer("问题", bundle, "grounded")
        assert gen.calls == 1
        assert len(sink) == 1
        block = sink[0]
        assert block.citation_id == "[C1]"
        assert block.chunk_id == "c1"
        assert block.source_name == "a.md"
        assert block.content == "内容1"
        assert block.retrieval_scores.get("sparse_score") == 0.9
        assert answer == "答案 [C1]"

    def test_grounded_valid_citation(self):
        bundle = EvidenceBundle.from_documents(
            [
                _rdoc("c1", "a.md", "内容1", rank=1, document_id="d1", score=0.9),
                _rdoc("c2", "b.md", "内容2", rank=2, document_id="d2", score=0.8),
            ],
            query_id="q",
            max_items=5,
        )
        gen = _FakeGenerator("结论 [C1]，补充 [C2]")
        adapter = PipelineAnswerAdapter(
            gen, direct_client=_FakeDirectClient(), direct_model="m"
        )
        assert adapter.answer("问题", bundle, "grounded") == "结论 [C1]，补充 [C2]"

    def test_grounded_invalid_citation_fails(self):
        gen = _FakeGenerator("答案 [C9]")  # 引用了不存在的 ID
        adapter = PipelineAnswerAdapter(
            gen, direct_client=_FakeDirectClient(), direct_model="m"
        )
        with pytest.raises(GenerationAdapterError):
            adapter.answer("问题", _one_item_bundle(), "grounded")

    def test_grounded_no_citation_fails(self):
        gen = _FakeGenerator("没有引用的答案")
        adapter = PipelineAnswerAdapter(
            gen, direct_client=_FakeDirectClient(), direct_model="m"
        )
        with pytest.raises(GenerationAdapterError):
            adapter.answer("问题", _one_item_bundle(), "grounded")

    @pytest.mark.parametrize(
        "error_str",
        [
            "[GENERATOR_TIMEOUT] 请求超时",
            "[GENERATOR_AUTH_ERROR] API key 无效",
            "[GENERATOR_UNAVAILABLE] HTTP 503",
            "[生成失败: RuntimeError] boom",
        ],
    )
    def test_grounded_rejects_error_strings(self, error_str):
        gen = _FakeGenerator(error_str)
        adapter = PipelineAnswerAdapter(
            gen, direct_client=_FakeDirectClient(), direct_model="m"
        )
        with pytest.raises(GenerationAdapterError):
            adapter.answer("问题", _one_item_bundle(), "grounded")


# ---------------------------------------------------------------------------
# 9/10. PipelineAnswerAdapter direct
# ---------------------------------------------------------------------------


class TestAnswerDirect:
    def test_direct_single_call(self):
        client = _FakeDirectClient(_FakeResp("42"))
        adapter = PipelineAnswerAdapter(
            _FakeGenerator(""), direct_client=client, direct_model="deepseek-chat"
        )
        answer = adapter.answer("1+1=?", EvidenceBundle.empty(), "direct")
        assert answer == "42"
        assert client.calls == 1
        kwargs = client.sink[0]
        assert kwargs["temperature"] == 0.0
        assert kwargs["max_tokens"] == 300
        assert kwargs["model"] == "deepseek-chat"

    def test_direct_defective_response_fails(self):
        for bad in (None, object(), _FakeResp(None), _FakeResp("   ")):
            client = _FakeDirectClient(bad)
            adapter = PipelineAnswerAdapter(
                _FakeGenerator(""), direct_client=client, direct_model="m"
            )
            with pytest.raises(GenerationAdapterError):
                adapter.answer("q", EvidenceBundle.empty(), "direct")

    def test_direct_client_error_fails(self):
        client = _FakeDirectClient(None, error=RuntimeError("boom"))
        adapter = PipelineAnswerAdapter(
            _FakeGenerator(""), direct_client=client, direct_model="m"
        )
        with pytest.raises(GenerationAdapterError):
            adapter.answer("q", EvidenceBundle.empty(), "direct")


# ---------------------------------------------------------------------------
# 11. 非法 Port 返回值 → 结构化 failed
# ---------------------------------------------------------------------------


class _Planner(BaseQueryPlanner):
    def __init__(self, result):
        self._result = result
        self.calls = 0

    def plan(self, q):
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _Retriever:
    def __init__(self, result):
        self._result = result
        self.calls = 0

    def search(self, q, strategy, top_k):
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _Answerer:
    def __init__(self, result):
        self._result = result
        self.calls = 0

    def answer(self, q, bundle, mode):
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class TestIllegalPortReturns:
    def test_planner_non_outcome_planning_failed(self):
        rt = AgentRuntime(
            planner=_Planner("not-an-outcome"),
            retrieval_port=_Retriever([]),
            answer_port=_Answerer("x"),
        )
        result = rt.run("q")
        assert result.status == "failed"
        assert result.error_code == "PLANNING_FAILED"
        assert result.planner_outcome is None
        assert result.trace[-1].data["exception_type"] == "InvalidPlannerOutcome"

    def test_retrieval_non_iterable_retrieval_failed(self):
        rt = AgentRuntime(
            planner=_Planner(_single_outcome()),
            retrieval_port=_Retriever(42),
            answer_port=_Answerer("x"),
        )
        result = rt.run("q")
        assert result.error_code == "RETRIEVAL_FAILED"
        assert result.answer is None

    def test_retrieval_bad_element_retrieval_failed(self):
        rt = AgentRuntime(
            planner=_Planner(_single_outcome()),
            retrieval_port=_Retriever([42]),
            answer_port=_Answerer("x"),
        )
        result = rt.run("q")
        assert result.error_code == "RETRIEVAL_FAILED"

    def test_answer_none_generation_failed(self):
        rt = AgentRuntime(
            planner=_Planner(_single_outcome()),
            retrieval_port=_Retriever([_rdoc("c1", "a.md", "内容", rank=1)]),
            answer_port=_Answerer(None),
        )
        result = rt.run("q")
        assert result.error_code == "GENERATION_FAILED"

    def test_answer_non_string_generation_failed(self):
        rt = AgentRuntime(
            planner=_Planner(_single_outcome()),
            retrieval_port=_Retriever([_rdoc("c1", "a.md", "内容", rank=1)]),
            answer_port=_Answerer(42),
        )
        result = rt.run("q")
        assert result.error_code == "GENERATION_FAILED"

    def test_answer_empty_string_generation_failed(self):
        rt = AgentRuntime(
            planner=_Planner(_single_outcome()),
            retrieval_port=_Retriever([_rdoc("c1", "a.md", "内容", rank=1)]),
            answer_port=_Answerer("   "),
        )
        result = rt.run("q")
        assert result.error_code == "GENERATION_FAILED"

    def test_no_extra_calls_after_illegal_return(self):
        planner = _Planner(_single_outcome())
        retriever = _Retriever([42])
        answerer = _Answerer("x")
        rt = AgentRuntime(planner=planner, retrieval_port=retriever, answer_port=answerer)
        result = rt.run("q")
        assert result.error_code == "RETRIEVAL_FAILED"
        assert planner.calls == 1
        assert retriever.calls == 1
        assert answerer.calls == 0


# ---------------------------------------------------------------------------
# 18. 调用次数断言 + 工厂
# ---------------------------------------------------------------------------


class TestFactory:
    def test_factory_completed_single_call_each(self):
        pipeline = SimpleNamespace(
            retriever=_bm25_retriever(), generator=_FakeGenerator("答案 [C1]")
        )
        planner_client = _FakePlannerClient(_SINGLE_PLAN_JSON)
        direct_client = _FakeDirectClient(_FakeResp("42"))
        rt = build_pipeline_agent_runtime(
            pipeline,
            planner_provider="deepseek",
            api_key="sk-test",
            planner_client=planner_client,
            direct_answer_client=direct_client,
        )
        result = rt.run("alpha", top_k=5)
        assert result.status == "completed"
        assert result.route_decision.route == "single_retrieval"
        assert result.sources == ("[C1]",)
        assert planner_client.calls == 1
        assert pipeline.generator.calls == 1
        assert direct_client.calls == 0  # grounded 不调用 direct

    def test_factory_deepseek_default_model(self):
        pipeline = SimpleNamespace(
            retriever=_bm25_retriever(), generator=_FakeGenerator("答案 [C1]")
        )
        planner_client = _FakePlannerClient(_SINGLE_PLAN_JSON)
        rt = build_pipeline_agent_runtime(
            pipeline,
            planner_provider="deepseek",
            api_key="sk-test",
            planner_client=planner_client,
            direct_answer_client=_FakeDirectClient(_FakeResp("42")),
        )
        rt.run("alpha")
        assert planner_client.sink[0]["model"] == "deepseek-chat"

    def test_factory_env_model_override(self, monkeypatch):
        monkeypatch.setenv("AGENT_PLANNER_MODEL", "custom-model")
        pipeline = SimpleNamespace(
            retriever=_bm25_retriever(), generator=_FakeGenerator("答案 [C1]")
        )
        planner_client = _FakePlannerClient(_SINGLE_PLAN_JSON)
        rt = build_pipeline_agent_runtime(
            pipeline,
            planner_provider="deepseek",
            api_key="sk-test",
            planner_client=planner_client,
            direct_answer_client=_FakeDirectClient(_FakeResp("42")),
        )
        rt.run("alpha")
        assert planner_client.sink[0]["model"] == "custom-model"

    def test_factory_deferred_preserves_subqueries(self):
        pipeline = SimpleNamespace(
            retriever=_bm25_retriever(), generator=_FakeGenerator("答案 [C1]")
        )
        rt = build_pipeline_agent_runtime(
            pipeline,
            planner_provider="deepseek",
            api_key="sk-test",
            planner_client=_FakePlannerClient(_DECOMPOSED_PLAN_JSON),
            direct_answer_client=_FakeDirectClient(_FakeResp("42")),
        )
        result = rt.run("alpha")
        assert result.status == "deferred"
        assert result.error_code == "DECOMPOSED_RETRIEVAL_NOT_IMPLEMENTED"
        assert result.route_decision.queries == ("甲", "乙")
        assert pipeline.generator.calls == 0

    def test_factory_no_key_leak(self):
        pipeline = SimpleNamespace(
            retriever=_bm25_retriever(), generator=_FakeGenerator("答案 [C1]")
        )
        rt = build_pipeline_agent_runtime(
            pipeline,
            planner_provider="deepseek",
            api_key="sk-super-secret",
            planner_client=_FakePlannerClient(_SINGLE_PLAN_JSON),
            direct_answer_client=_FakeDirectClient(_FakeResp("42")),
        )
        assert "sk-super-secret" not in repr(rt)
        assert "sk-super-secret" not in repr(rt._planner)
        result = rt.run("alpha")
        blob = json.dumps(result.to_dict(), ensure_ascii=False)
        assert "sk-super-secret" not in blob
