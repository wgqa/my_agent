"""G3-RUNTIME-05B：Agent Runtime 生产 Adapter 与工厂。

把现有 Pipeline 的 Retriever / Generator 包装成 Runtime 的 RetrievalPort /
AnswerPort Adapter，并提供 build_pipeline_agent_runtime 工厂。本模块只做
“接线”，不实现新的检索/生成算法；不读取 Dev/Holdout，不联网（Fake 注入
时）。direct 模式只用问题自身信息，禁止外部知识；grounded 模式依赖
CitationValidator 保证答案可溯源。
"""

from __future__ import annotations

import os
from typing import Optional, Sequence

from openai import OpenAI

from core.agent_runtime.models import (
    Document as RuntimeDocument,
    EvidenceBundle,
    validate_answer_mode,
)
from core.agent_runtime.runtime import AgentRuntime
from core.conversation_context import OpenAICompatibleConversationQueryResolver
from core.context.assembler import ContextBlock
from core.generator.citation import CitationValidator
from core.loader.base import Document as LoaderDocument
from core.query_planning.openai_compatible import OpenAICompatibleQueryPlanner
from core.retriever.bm25_only import BM25OnlyRetriever
from core.retriever.hybrid import HybridRetriever

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DIRECT_TIMEOUT_SECONDS = 20.0
DIRECT_MAX_TOKENS = 300

# direct 模式：只允许处理问题自身给出的信息（确定性运算/排序/字符串转换）。
DIRECT_ANSWER_SYSTEM_PROMPT = (
    "你是一个只处理问题自身信息的确定性计算器。\n"
    "规则：\n"
    "1. 只使用问题中直接给出的信息（数字、列表、字符串），"
    "不引入任何外部知识、常识或记忆；\n"
    "2. 只做确定性运算、排序或字符串转换，不推断、不联想；\n"
    "3. 直接输出结果，不展示任何思考过程；\n"
    "4. 问题信息不足时，明确回答无法计算。"
)

# Generator 的错误占位字符串（deepseek_gen / openai_gen 失败分支产出）。
GENERATOR_ERROR_MARKERS = ("[GENERATOR_", "[生成失败")


class UnsupportedRetrievalStrategyError(RuntimeError):
    """当前 Adapter 只支持 BM25（Hybrid 的 sparse 或 BM25Only）。"""


class GenerationAdapterError(RuntimeError):
    """生成适配失败：错误占位字符串 / 无效引用 / 响应缺损 / 空结果。"""


def _extract_direct_content(response: object) -> str:
    """逐层检查 OpenAI-compatible 响应结构；任何缺损抛 GenerationAdapterError。"""
    try:
        choices = response.choices
    except AttributeError as exc:
        raise GenerationAdapterError("direct 响应 choices 缺失") from exc
    if not isinstance(choices, list) or not choices:
        raise GenerationAdapterError("direct 响应 choices 为空")
    try:
        message = choices[0].message
    except AttributeError as exc:
        raise GenerationAdapterError("direct 响应 message 缺失") from exc
    if message is None:
        raise GenerationAdapterError("direct 响应 message 为空")
    try:
        content = message.content
    except AttributeError as exc:
        raise GenerationAdapterError("direct 响应 content 缺失") from exc
    return content


class PipelineRetrievalAdapter:
    """把现有 Retriever 包装成 RetrievalPort（支持 bm25 / hybrid）。

    能力声明 supported_strategies：HybridRetriever → ("bm25", "hybrid")；
    BM25OnlyRetriever → ("bm25",)；其他 → ()。
    bm25 + HybridRetriever → retrieve_sparse()；hybrid + HybridRetriever →
    retrieve()（真实 Dense+Sparse+RRF）；bm25 + BM25OnlyRetriever →
    retrieve()；其余组合抛 UnsupportedRetrievalStrategyError。
    Hybrid 结果的 score 用真实 rrf_score；BM25 用 sparse_score，不得虚构。
    """

    def __init__(self, retriever) -> None:
        self._retriever = retriever
        if isinstance(retriever, HybridRetriever):
            self._supported = ("bm25", "hybrid")
        elif isinstance(retriever, BM25OnlyRetriever):
            self._supported = ("bm25",)
        else:
            self._supported = ()

    @property
    def supported_strategies(self) -> tuple[str, ...]:
        return self._supported

    def search(
        self, query: str, strategy: str, top_k: int
    ) -> Sequence[RuntimeDocument]:
        retriever = self._retriever
        if strategy == "bm25":
            if isinstance(retriever, HybridRetriever) and hasattr(
                retriever, "retrieve_sparse"
            ):
                raw_docs = retriever.retrieve_sparse(query, top_k=top_k)
                score_key = "sparse_score"
            elif isinstance(retriever, BM25OnlyRetriever):
                raw_docs = retriever.retrieve(query, top_k=top_k)
                score_key = "sparse_score"
            else:
                raise UnsupportedRetrievalStrategyError(
                    f"不支持的 Retriever：{type(retriever).__name__}（bm25 只支持 "
                    "HybridRetriever 与 BM25OnlyRetriever）"
                )
        elif strategy == "hybrid":
            if isinstance(retriever, HybridRetriever):
                raw_docs = retriever.retrieve(query, top_k=top_k)
                score_key = "rrf_score"
            else:
                raise UnsupportedRetrievalStrategyError(
                    f"不支持的 Retriever：{type(retriever).__name__}（hybrid "
                    "只支持 HybridRetriever）"
                )
        else:
            raise UnsupportedRetrievalStrategyError(
                f"不支持的 strategy {strategy!r}（只支持 bm25 / hybrid）"
            )
        mapped = []
        for rank, doc in enumerate(raw_docs, 1):
            if not isinstance(doc, LoaderDocument):
                raise TypeError(
                    f"检索结果每项必须是 loader.Document，实际 "
                    f"{type(doc).__name__}"
                )
            mapped.append(self._map_document(doc, rank, score_key))
        return tuple(mapped)

    @staticmethod
    def _map_document(
        doc: LoaderDocument, rank: int, score_key: str = "sparse_score"
    ) -> RuntimeDocument:
        meta = doc.metadata or {}
        source_name = meta.get("source_name", meta.get("source"))
        if source_name is None or not str(source_name).strip():
            raise ValueError("检索结果缺少 source_name，禁止虚构来源")
        chunk_id = meta.get("id")
        document_id = meta.get("document_id")
        score = meta.get(score_key)
        return RuntimeDocument(
            chunk_id=chunk_id,
            document_id=document_id,
            source_name=str(source_name),
            content=doc.content,
            score=score,
            rank=rank,
        )


class PipelineAnswerAdapter:
    """把现有 Generator（grounded）与 OpenAI-compatible Client（direct）
    包装成 AnswerPort。

    grounded：EvidenceBundle.items → ContextBlock（保持 citation_id）→
    generator.generate(question, blocks) → CitationValidator 校验：必须至少
    一个有效引用且无无效引用；错误占位字符串（[GENERATOR_*] / [生成失败）
    一律视为 Generation Adapter 失败。
    direct：单次调用、temperature=0、max_retries=0、timeout 有界、
    max_tokens=300，只用问题自身信息，响应必须为非空字符串。
    两条路径各自只调用一次生成能力。api_key 不保存在实例字段上。
    """

    def __init__(
        self,
        generator,
        *,
        direct_client=None,
        direct_model: Optional[str] = None,
        direct_api_key: Optional[str] = None,
        direct_base_url: Optional[str] = None,
        direct_timeout: float = DIRECT_TIMEOUT_SECONDS,
        direct_max_tokens: int = DIRECT_MAX_TOKENS,
    ) -> None:
        self._generator = generator
        self._direct_model = direct_model
        self._direct_max_tokens = direct_max_tokens
        if direct_client is not None:
            self._direct_client = direct_client
        else:
            # api_key 只传给 SDK client，不保存在 self 上（repr/日志不泄漏）。
            kwargs = {
                "api_key": direct_api_key,
                "timeout": direct_timeout,
                "max_retries": 0,
            }
            if direct_base_url:
                kwargs["base_url"] = direct_base_url
            self._direct_client = OpenAI(**kwargs)

    def answer(
        self,
        question: str,
        evidence_bundle: EvidenceBundle,
        mode: str,
    ) -> str:
        validate_answer_mode(mode)
        if mode == "direct":
            return self._answer_direct(question)
        return self._answer_grounded(question, evidence_bundle)

    def _answer_direct(self, question: str) -> str:
        if self._direct_model is None:
            raise GenerationAdapterError("direct 模式未配置模型")
        messages = [
            {"role": "system", "content": DIRECT_ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        try:
            response = self._direct_client.chat.completions.create(
                model=self._direct_model,
                messages=messages,
                temperature=0.0,
                max_tokens=self._direct_max_tokens,
            )
        except Exception as exc:
            raise GenerationAdapterError("direct 生成调用失败") from exc
        content = _extract_direct_content(response)
        if type(content) is not str or not content.strip():
            raise GenerationAdapterError("direct 生成结果为空")
        return content

    def _answer_grounded(
        self, question: str, evidence_bundle: EvidenceBundle
    ) -> str:
        blocks = self._build_context_blocks(evidence_bundle)
        answer = self._generator.generate(question, blocks)
        if type(answer) is not str or not answer.strip():
            raise GenerationAdapterError("Generator 返回空结果")
        if self._is_generator_error_string(answer):
            raise GenerationAdapterError("Generator 返回错误占位字符串")
        validation = CitationValidator().validate(answer, blocks)
        if not validation.valid or validation.invalid:
            raise GenerationAdapterError("答案缺少有效引用或存在无效引用")
        return answer

    @staticmethod
    def _build_context_blocks(
        evidence_bundle: EvidenceBundle,
    ) -> list[ContextBlock]:
        blocks = []
        for item in evidence_bundle.items:
            retrieval_scores = {}
            if item.score is not None:
                retrieval_scores["sparse_score"] = item.score
            blocks.append(
                ContextBlock(
                    citation_id=item.citation_id,
                    chunk_id=item.chunk_id or "",
                    source_name=item.source_name,
                    page_number=None,
                    content=item.content,
                    token_count=len(item.content),
                    retrieval_scores=retrieval_scores,
                )
            )
        return blocks

    @staticmethod
    def _is_generator_error_string(answer: str) -> bool:
        return any(answer.startswith(marker) for marker in GENERATOR_ERROR_MARKERS)


def build_pipeline_agent_runtime(
    pipeline,
    *,
    planner_provider: str,
    planner_model: Optional[str] = None,
    api_key: str,
    base_url: Optional[str] = None,
    planner_client=None,
    direct_answer_client=None,
    context_resolver_client=None,
) -> AgentRuntime:
    """用真实 Pipeline 的 Retriever / Generator 组装一个 AgentRuntime。

    planner_model 解析顺序：AGENT_PLANNER_MODEL 环境变量 > 显式
    planner_model > DeepSeek 默认 deepseek-chat。DeepSeek 默认 base_url 用
    项目已有官方地址。api_key 只传给 SDK client / Provider，不写入任何实例
    可见字段；planner_client / direct_answer_client 用于测试注入（不联网）。
    """
    provider = str(planner_provider)
    model = (
        os.getenv("AGENT_PLANNER_MODEL")
        or planner_model
        or ("deepseek-chat" if provider.lower() == "deepseek" else None)
    )
    if not model:
        raise ValueError("planner_model 未提供（可传参或设置 AGENT_PLANNER_MODEL）")
    resolved_base_url = base_url or (
        DEEPSEEK_BASE_URL if provider.lower() == "deepseek" else None
    )

    planner = OpenAICompatibleQueryPlanner(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=resolved_base_url,
        client=planner_client,
    )
    retrieval = PipelineRetrievalAdapter(pipeline.retriever)
    answer = PipelineAnswerAdapter(
        pipeline.generator,
        direct_client=direct_answer_client,
        direct_model=model,
        direct_api_key=api_key,
        direct_base_url=resolved_base_url,
    )
    resolver = OpenAICompatibleConversationQueryResolver(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=resolved_base_url,
        client=context_resolver_client,
    )
    return AgentRuntime(
        planner=planner,
        retrieval_port=retrieval,
        answer_port=answer,
        query_resolver=resolver,
    )
