"""G3-E2E-07A：Gate 3 第一次真实完整链路 Answer + Citation 评测。

在公开 Gate 3 Dev 24 Case 上跑真实链路：

  Real Planner(deepseek, gate3_planner_prompt_v1)
  → Adaptive Router v1 → Retrieval(冻结语料 Hybrid)
  → subquery_rrf_merge_v2(k=60) → Evidence Verifier
  → Real Generator(grounded, 引用标注) → Citation Validator → Answer

严格两阶段与 Gold 隔离：
  Generation stage  只接触 (case_id, query) / Planner 输出 / 检索 Evidence /
                    正常 runtime 输入，绝不接触 Gold obligation / relevant_file
                    / expected answer / evaluator rubric；原始生成结果先持久化。
  Evaluation stage  离线读取 Dev Gold，做确定性指标 + LLM Judge
                    (gate3_answer_judge_prompt_v1，结构化 covered/not_covered)。

本模块不读取 sealed/Holdout；不调用 Holdout；不跑 A/B/C 竞赛；不做调参。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from dotenv import load_dotenv
from openai import OpenAI

from core.adaptive_retrieval import ADAPTIVE_RETRIEVAL_POLICY_VERSION
from core.agent_runtime import (
    DEFAULT_MERGE_RRF_K,
    SUBQUERY_RRF_MERGE_V2,
    AgentRunBudget,
    AgentRuntime,
    EvidenceBundle,
    PipelineRetrievalAdapter,
)
from core.agent_runtime.adapters import (
    DIRECT_ANSWER_SYSTEM_PROMPT,
    DIRECT_MAX_TOKENS,
    DIRECT_TIMEOUT_SECONDS,
    GenerationAdapterError,
    PipelineAnswerAdapter,
    _extract_direct_content,
)
from core.agent_runtime.models import validate_answer_mode
from core.generator.deepseek_gen import DeepSeekGenerator
from core.query_planning.openai_compatible import OpenAICompatibleQueryPlanner
from core.query_planning.prompt import (
    PLANNER_MAX_OUTPUT_TOKENS,
    PLANNER_MAX_RETRIES,
    PLANNER_PROMPT_SHA256,
    PLANNER_PROMPT_VERSION,
    PLANNER_TEMPERATURE,
    PLANNER_TIMEOUT_SECONDS,
)
from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.gate3.adaptive_dev import (
    EXPECTED_CORPUS_FILE_COUNT,
    EXPECTED_CORPUS_ID,
    EXPECTED_DEV_CASE_COUNT,
    EXPECTED_DEV_EVALUATION_SET_ID,
    EXPECTED_DEV_JSONL_SHA256,
    EXPECTED_FREEZE_ID,
    _canonical_json,
    _check_hex,
    _check_nonempty_no_ws,
    _safe_rate,
    _sha256_bytes,
    _sha256_file,
    build_shared_index,
    canonical_paths_from_documents,
    check_git_tracked_clean,
    compute_document_metrics,
    compute_obligation_metrics,
    load_corpus,
    write_text_atomic,
)
from evaluation.gate3.evaluation_set import Gate3EvaluationSet

GATE3_E2E_SCHEMA_VERSION = "gate3_e2e_run_v1"
GATE3_E2E_METRICS_SCHEMA_VERSION = "gate3_e2e_metrics_v1"
GATE3_E2E_RESULT_SCHEMA_VERSION = "gate3_e2e_result_v1"
GATE3_E2E_MANIFEST_SCHEMA_VERSION = "gate3_e2e_index_manifest_v1"
GATE3_E2E_JUDGMENT_SCHEMA_VERSION = "gate3_e2e_judgment_v1"

# LLM Judge（evaluation-only，生成完成后才读取 query/answer/cited evidence/Gold）。
GATE3_ANSWER_JUDGE_PROMPT_VERSION = "gate3_answer_judge_prompt_v1"
GATE3_ANSWER_JUDGE_SYSTEM_PROMPT = (
    "你是 RAG 答案评测器。只做两件事：\n"
    "1. 对每个给定的 Gold obligation，判断生成答案是否覆盖了该义务要求回答的方面，"
    "输出结构化 covered / not_covered；\n"
    "2. 判断答案是否存在明显的、被引用证据无法支撑的实质性事实主张"
    "（unsupported material claim）。\n"
    "只输出一行严格 JSON，不要输出任何其它文字。\n"
    "JSON schema："
    '{"obligation_coverage": {"o1": "covered", "o2": "not_covered"}, '
    '"unsupported_material_claims": ["claim1"]}\n'
    "判断依据：Gold obligation 的 description 描述该义务必须覆盖的方面；"
    "答案是否覆盖它。\n"
    "答案中被 [Cx] 引用的证据块列在 evidence 里；答案里没有被证据支撑的实质性"
    "事实主张应列入 unsupported_material_claims（没有则为空数组）。"
)
GATE3_ANSWER_JUDGE_PROMPT_SHA256 = _sha256_bytes(
    GATE3_ANSWER_JUDGE_SYSTEM_PROMPT.encode("utf-8")
)

JUDGE_COVERED = "covered"
JUDGE_NOT_COVERED = "not_covered"
JUDGE_COVERAGE_VALUES = (JUDGE_COVERED, JUDGE_NOT_COVERED)

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Authorization\s*[:=]"),
    re.compile(r"DEEPSEEK_API_KEY\s*="),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}"),
)


def _reject_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"重复 key: {key!r}")
        out[key] = value
    return out


def _citation_int(citation_id: str) -> int:
    if not (citation_id.startswith("[C") and citation_id.endswith("]")):
        raise ValueError(f"非法 citation_id: {citation_id!r}")
    return int(citation_id[2:-1])


# ---------------------------------------------------------------------------
# 配置与身份
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate3E2EConfig:
    """一次 Gate 3 E2E 运行的强类型配置；run_id 由身份载荷计算。

    identity 绑定：语料/Dev/freeze 身份 + 检索/merge 参数 + Planner 配置 +
    Generator 配置 + Judge 配置。执行路径不进身份。
    """

    schema_version: str = GATE3_E2E_SCHEMA_VERSION
    source_commit: str = ""
    corpus_id: str = ""
    corpus_file_count: int = 0
    gate3_dataset_freeze_id: str = ""
    dev_evaluation_set_id: str = ""
    dev_case_count: int = 0
    dev_jsonl_sha256: str = ""
    # 检索 / merge（沿用 06C 生产候选 D）
    chunk_strategy: str = "recursive"
    chunk_budget_policy: str = "cl100k_content_v1"
    chunk_size: int = 512
    chunk_overlap: int = 64
    embedding_provider: str = "bge"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    dense_candidate_k: int = 30
    sparse_candidate_k: int = 30
    rrf_k: float = 60.0
    rrf_tie_breaker: str = "chunk_id_asc"
    top_k: int = 5
    max_evidence_items: int = 5
    max_retrieval_calls: int = 4
    merge_policy: str = SUBQUERY_RRF_MERGE_V2
    merge_rrf_k: float = DEFAULT_MERGE_RRF_K
    group_d_policy: str = ADAPTIVE_RETRIEVAL_POLICY_VERSION
    # Planner（真实在线 Planner）
    planner_provider: str = "deepseek"
    planner_model: str = "deepseek-chat"
    planner_temperature: float = PLANNER_TEMPERATURE
    planner_timeout: float = PLANNER_TIMEOUT_SECONDS
    planner_max_tokens: int = PLANNER_MAX_OUTPUT_TOKENS
    planner_max_retries: int = PLANNER_MAX_RETRIES
    planner_prompt_version: str = PLANNER_PROMPT_VERSION
    planner_prompt_sha256: str = PLANNER_PROMPT_SHA256
    # Generator（真实 Generator，grounded）
    generator_provider: str = "deepseek"
    generator_model: str = "deepseek-v4-flash"
    generator_temperature: float = 0.3
    generator_timeout: float = 60.0
    generator_max_tokens: int = 800
    generator_max_retries: int = 2
    generator_prompt_version: str = "gate3_generator_prompt_v1"
    # Judge（evaluation-only）
    judge_provider: str = "deepseek"
    judge_model: str = "deepseek-chat"
    judge_temperature: float = 0.0
    judge_timeout: float = 60.0
    judge_max_tokens: int = 800
    judge_max_retries: int = 2
    judge_prompt_version: str = GATE3_ANSWER_JUDGE_PROMPT_VERSION
    judge_prompt_sha256: str = GATE3_ANSWER_JUDGE_PROMPT_SHA256
    # 执行路径（不进 run_id 身份）
    dev_jsonl_path: str = ""
    frozen_index_manifest_path: str = ""
    corpus_root: str = ""
    output_dir: str = ""

    def __post_init__(self) -> None:
        _check_hex(self.source_commit, 40, "source_commit")
        _check_hex(self.corpus_id, 12, "corpus_id")
        _check_hex(self.gate3_dataset_freeze_id, 12, "gate3_dataset_freeze_id")
        _check_hex(self.dev_evaluation_set_id, 12, "dev_evaluation_set_id")
        _check_hex(self.dev_jsonl_sha256, 64, "dev_jsonl_sha256")
        _check_hex(self.planner_prompt_sha256, 64, "planner_prompt_sha256")
        _check_hex(self.judge_prompt_sha256, 64, "judge_prompt_sha256")
        for name, retry in (
            ("corpus_file_count", False), ("dev_case_count", False),
            ("chunk_size", False), ("chunk_overlap", False),
            ("dense_candidate_k", False), ("sparse_candidate_k", False),
            ("top_k", False), ("max_evidence_items", False),
            ("max_retrieval_calls", False),
            ("planner_max_tokens", False), ("generator_max_tokens", False),
            ("judge_max_tokens", False),
            ("planner_max_retries", True), ("generator_max_retries", True),
            ("judge_max_retries", True),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} 必须是整数（不允许 bool）")
            if value < 0 if retry else value <= 0:
                raise ValueError(f"{name} 取值非法：{value}")
        for label in (
            "chunk_strategy", "chunk_budget_policy", "embedding_provider",
            "embedding_model", "rrf_tie_breaker", "merge_policy",
            "group_d_policy", "planner_provider", "planner_model",
            "planner_prompt_version", "generator_provider", "generator_model",
            "generator_prompt_version", "judge_provider", "judge_model",
            "judge_prompt_version",
        ):
            _check_nonempty_no_ws(getattr(self, label), label)
        for label, value in (
            ("planner_temperature", self.planner_temperature),
            ("generator_temperature", self.generator_temperature),
            ("judge_temperature", self.judge_temperature),
        ):
            if isinstance(value, bool) or type(value) not in (int, float):
                raise TypeError(f"{label} 必须是 int/float（不允许 bool）")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{label} 必须是有界非负数")
        for label, value in (
            ("planner_timeout", self.planner_timeout),
            ("generator_timeout", self.generator_timeout),
            ("judge_timeout", self.judge_timeout),
            ("merge_rrf_k", self.merge_rrf_k),
            ("rrf_k", self.rrf_k),
        ):
            if isinstance(value, bool) or type(value) not in (int, float):
                raise TypeError(f"{label} 必须是 int/float（不允许 bool）")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} 必须是有界正数")

    def identity_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "corpus_id": self.corpus_id,
            "corpus_file_count": self.corpus_file_count,
            "gate3_dataset_freeze_id": self.gate3_dataset_freeze_id,
            "dev_evaluation_set_id": self.dev_evaluation_set_id,
            "dev_case_count": self.dev_case_count,
            "dev_jsonl_sha256": self.dev_jsonl_sha256,
            "chunk_strategy": self.chunk_strategy,
            "chunk_budget_policy": self.chunk_budget_policy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "dense_candidate_k": self.dense_candidate_k,
            "sparse_candidate_k": self.sparse_candidate_k,
            "rrf_k": self.rrf_k,
            "rrf_tie_breaker": self.rrf_tie_breaker,
            "top_k": self.top_k,
            "max_evidence_items": self.max_evidence_items,
            "max_retrieval_calls": self.max_retrieval_calls,
            "merge_policy": self.merge_policy,
            "merge_rrf_k": self.merge_rrf_k,
            "group_d_policy": self.group_d_policy,
            "planner_provider": self.planner_provider,
            "planner_model": self.planner_model,
            "planner_temperature": self.planner_temperature,
            "planner_timeout": self.planner_timeout,
            "planner_max_tokens": self.planner_max_tokens,
            "planner_max_retries": self.planner_max_retries,
            "planner_prompt_version": self.planner_prompt_version,
            "planner_prompt_sha256": self.planner_prompt_sha256,
            "generator_provider": self.generator_provider,
            "generator_model": self.generator_model,
            "generator_temperature": self.generator_temperature,
            "generator_timeout": self.generator_timeout,
            "generator_max_tokens": self.generator_max_tokens,
            "generator_max_retries": self.generator_max_retries,
            "generator_prompt_version": self.generator_prompt_version,
            "judge_provider": self.judge_provider,
            "judge_model": self.judge_model,
            "judge_temperature": self.judge_temperature,
            "judge_timeout": self.judge_timeout,
            "judge_max_tokens": self.judge_max_tokens,
            "judge_max_retries": self.judge_max_retries,
            "judge_prompt_version": self.judge_prompt_version,
            "judge_prompt_sha256": self.judge_prompt_sha256,
        }

    @property
    def run_id(self) -> str:
        return _sha256_bytes(_canonical_json(self.identity_payload()))[:12]

    def to_dict(self) -> dict:
        payload = dict(self.identity_payload())
        payload["run_id"] = self.run_id
        for name in (
            "dev_jsonl_path", "frozen_index_manifest_path", "corpus_root",
            "output_dir",
        ):
            payload[name] = "set" if getattr(self, name) else ""
        return payload


def validate_identity(config: Gate3E2EConfig) -> None:
    """验证冻结身份；任何不一致 fail-fast（在读取/运行前）。"""
    for attr, expected, label in (
        ("corpus_id", EXPECTED_CORPUS_ID, "corpus_id"),
        ("corpus_file_count", EXPECTED_CORPUS_FILE_COUNT, "corpus_file_count"),
        ("gate3_dataset_freeze_id", EXPECTED_FREEZE_ID, "gate3_dataset_freeze_id"),
        ("dev_evaluation_set_id", EXPECTED_DEV_EVALUATION_SET_ID,
         "dev_evaluation_set_id"),
        ("dev_case_count", EXPECTED_DEV_CASE_COUNT, "dev_case_count"),
        ("dev_jsonl_sha256", EXPECTED_DEV_JSONL_SHA256, "dev_jsonl_sha256"),
    ):
        if getattr(config, attr) != expected:
            raise ValueError(f"{label} 必须是 {expected}，实际 {getattr(config, attr)}")
    if config.planner_prompt_sha256 != PLANNER_PROMPT_SHA256:
        raise ValueError("planner_prompt_sha256 必须等于冻结 prompt SHA")
    if config.judge_prompt_sha256 != GATE3_ANSWER_JUDGE_PROMPT_SHA256:
        raise ValueError("judge_prompt_sha256 必须等于冻结 judge prompt SHA")

    actual_dev_sha = _sha256_file(Path(config.dev_jsonl_path))
    if actual_dev_sha != config.dev_jsonl_sha256:
        raise ValueError(
            f"dev jsonl 实际 SHA {actual_dev_sha} 与配置 {config.dev_jsonl_sha256} 不一致"
        )


# ---------------------------------------------------------------------------
# Generation Case（Gold 隔离边界）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GenerationCase:
    """Generation stage 的唯一 Case 视图：只含 case_id + query，绝不含 Gold。"""

    case_id: str
    query: str


def load_generation_cases(dev_jsonl_path: str) -> list[GenerationCase]:
    """从 Dev JSONL 读取生成所需的 (case_id, query)，剥离一切 Gold 字段。

    这是 Gold 隔离的硬边界：本函数只接受 case_id/query，生成链路上不可能
    带上 Gold obligation / relevant_files / 答案标注。
    """
    cases: list[GenerationCase] = []
    seen: set[str] = set()
    with open(dev_jsonl_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"第 {lineno} 行必须是 JSON object")
            case_id = obj.get("case_id")
            query = obj.get("query")
            if type(case_id) is not str or type(query) is not str:
                raise ValueError(f"第 {lineno} 行缺少 case_id/query")
            if case_id in seen:
                raise ValueError(f"第 {lineno} 行 case_id 重复: {case_id}")
            seen.add(case_id)
            cases.append(GenerationCase(case_id=case_id, query=query))
    if not cases:
        raise ValueError("Dev JSONL 不含任何 case")
    return cases


# ---------------------------------------------------------------------------
# 真实 AnswerPort（复用真实 Generator；Citation 有效性由离线评测层度量）
# ---------------------------------------------------------------------------


class E2EGroundedAnswerPort:
    """真实 Generator 的薄 AnswerPort：grounded 复用现有 generator + 上下文
    拼接；direct 复用 DIRECT_ANSWER_SYSTEM_PROMPT + OpenAI-compatible client。

    与 PipelineAnswerAdapter 的唯一差别：不在 port 里把 citation 校验做成
    硬失败（citation 有效性是 07A 的确定性指标，由离线评测层单独度量）。
    复用其 context block 构建与 generator 错误占位串识别。
    """

    answer_generation = "grounded"
    answer_adapter = "e2e_grounded_v1"

    def __init__(
        self,
        generator,
        *,
        direct_client=None,
        direct_model: Optional[str] = None,
        direct_api_key: Optional[str] = None,
        direct_base_url: Optional[str] = None,
    ):
        self._generator = generator
        self._direct_model = direct_model
        if direct_client is not None:
            self._direct_client = direct_client
        else:
            kwargs = {
                "api_key": direct_api_key,
                "timeout": DIRECT_TIMEOUT_SECONDS,
                "max_retries": 0,
            }
            if direct_base_url:
                kwargs["base_url"] = direct_base_url
            self._direct_client = OpenAI(**kwargs)

    def answer(self, question: str, evidence_bundle: EvidenceBundle, mode: str) -> str:
        validate_answer_mode(mode)
        if mode == "direct":
            return self._answer_direct(question)
        return self._answer_grounded(question, evidence_bundle)

    def _answer_grounded(self, question: str, evidence_bundle: EvidenceBundle) -> str:
        blocks = PipelineAnswerAdapter._build_context_blocks(evidence_bundle)
        answer = self._generator.generate(question, blocks)
        if PipelineAnswerAdapter._is_generator_error_string(answer):
            raise GenerationAdapterError("Generator 返回错误占位字符串")
        return answer

    def _answer_direct(self, question: str) -> str:
        messages = [
            {"role": "system", "content": DIRECT_ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        try:
            response = self._direct_client.chat.completions.create(
                model=self._direct_model,
                messages=messages,
                temperature=0.0,
                max_tokens=DIRECT_MAX_TOKENS,
            )
        except Exception as exc:
            raise GenerationAdapterError("direct 生成调用失败") from exc
        content = _extract_direct_content(response)
        if type(content) is not str or not content.strip():
            raise GenerationAdapterError("direct 生成结果为空")
        return content


# ---------------------------------------------------------------------------
# Citation 解析 / 校验（确定性层）
# ---------------------------------------------------------------------------


def parse_citations(answer: Optional[str]) -> set[int]:
    """解析答案中的 [Cx] 引用编号集合。"""
    if type(answer) is not str:
        return set()
    return {int(m) for m in re.findall(r"\[C(\d+)\]", answer)}


def evaluate_citations(
    answer: Optional[str], evidence_citation_ids: Sequence[int]
) -> dict:
    """确定性 citation 校验：cited / valid / invalid / uncited。"""
    cited = parse_citations(answer) if answer else set()
    available = set(evidence_citation_ids)
    invalid = sorted(cited - available)
    uncited = sorted(available - cited)
    valid = sorted(cited - set(invalid))
    return {
        "cited_count": len(cited),
        "valid_count": len(valid),
        "invalid_count": len(invalid),
        "invalid_ids": invalid,
        "uncited_evidence_count": len(uncited),
        "uncited_ids": uncited,
    }


# ---------------------------------------------------------------------------
# Judge（evaluation-only，结构化输出）
# ---------------------------------------------------------------------------


def parse_judge_output(raw: str) -> dict:
    """严格解析 Judge 输出为结构化结果；任何缺损 raise ValueError。

    返回 {"obligation_coverage": {oid: covered/not_covered},
          "unsupported_material_claims": [str, ...]}。
    """
    if type(raw) is not str or not raw.strip():
        raise ValueError("Judge 输出为空")
    obj = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    if not isinstance(obj, dict):
        raise ValueError("Judge 输出必须是 JSON object")
    coverage = obj.get("obligation_coverage")
    if not isinstance(coverage, dict) or not coverage:
        raise ValueError("obligation_coverage 必须是非空 object")
    normalized: dict[str, str] = {}
    for oid, val in coverage.items():
        if type(oid) is not str or val not in JUDGE_COVERAGE_VALUES:
            raise ValueError(f"obligation_coverage 非法条目: {oid!r}={val!r}")
        normalized[oid] = val
    claims = obj.get("unsupported_material_claims", [])
    if not isinstance(claims, list) or not all(
        isinstance(c, str) for c in claims
    ):
        raise ValueError("unsupported_material_claims 必须是字符串数组")
    return {
        "obligation_coverage": normalized,
        "unsupported_material_claims": list(claims),
    }


class AnswerJudge:
    """evaluation-only LLM Judge：只在生成完成后调用；不改变答案。"""

    def __init__(
        self,
        *,
        config: Gate3E2EConfig,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        client=None,
    ):
        self._config = config
        if client is not None:
            self._client = client
        else:
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=config.judge_timeout,
                max_retries=0,
            )

    def judge(self, question: str, answer: str, cited_evidence: list,
              gold_obligations: list) -> dict:
        messages = [
            {"role": "system", "content": GATE3_ANSWER_JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": _build_judge_user_message(
                question, answer, cited_evidence, gold_obligations)},
        ]
        last_error = None
        for _ in range(self._config.judge_max_retries + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self._config.judge_model,
                    messages=messages,
                    temperature=self._config.judge_temperature,
                    max_tokens=self._config.judge_max_tokens,
                )
                raw = resp.choices[0].message.content
                if type(raw) is not str:
                    return {"judge_status": "invalid", "reason": "empty_output"}
                parsed = parse_judge_output(raw)
                return {"judge_status": "ok", **parsed}
            except ValueError:
                return {"judge_status": "invalid", "reason": "unparseable"}
            except Exception as exc:
                last_error = exc
        return {"judge_status": "invalid",
                "reason": f"provider_error:{type(last_error).__name__}"}


def _build_judge_user_message(question, answer, cited_evidence, gold_obligations) -> str:
    ev_lines = []
    for item in cited_evidence:
        ev_lines.append(
            f"[{item.get('citation_id')}] (来源: {item.get('source_name')})\n"
            f"{item.get('content', '')}"
        )
    obl_lines = [
        f"- {o['obligation_id']}: {o['description']}" for o in gold_obligations
    ]
    return (
        f"<question>\n{question}\n</question>\n\n"
        f"<answer>\n{answer}\n</answer>\n\n"
        f"<evidence>\n{chr(10).join(ev_lines) if ev_lines else '(无被引用证据)'}\n</evidence>\n\n"
        f"<gold_obligations>\n{chr(10).join(obl_lines) if obl_lines else '(无)'}\n</gold_obligations>"
    )


# ---------------------------------------------------------------------------
# Artifact 安全与写入
# ---------------------------------------------------------------------------


def assert_no_secrets(text: str) -> None:
    """Artifact 安全红线：不得包含真实 API Key / Authorization 头 / 敏感 env 名。"""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            raise ValueError(f"Artifact 含敏感信息: {pattern.pattern!r}")


def _redacted_plan(plan) -> dict:
    if plan is None:
        return {"query_type": None, "action": None, "reason_code": None,
                "subquery_count": 0}
    return {
        "query_type": plan.query_type,
        "action": plan.action,
        "reason_code": plan.reason_code,
        "subquery_count": len(plan.subqueries),
    }


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


class _RecordingRetrievalPort:
    """记录每次 search 返回结果的 RetrievalPort 包装（用于 candidate 覆盖）。"""

    def __init__(self, inner, sink: list):
        self._inner = inner
        self._sink = sink

    @property
    def supported_strategies(self):
        return self._inner.supported_strategies

    def search(self, query, strategy, top_k):
        docs = self._inner.search(query, strategy, top_k)
        self._sink.append({"query": query, "strategy": strategy, "docs": list(docs)})
        return docs


def run_e2e_generation(config: Gate3E2EConfig, git_head: str) -> dict:
    """Generation stage：真实 Planner→Router→Retrieval→merge v2→Verifier→
    真实 Generator→Answer；只接触 (case_id, query)，先持久化原始生成结果。"""
    if config.source_commit != git_head:
        raise ValueError(
            f"source_commit {config.source_commit} 与 git HEAD {git_head} 不一致"
        )
    validate_identity(config)

    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量")

    corpus_path = Path(config.corpus_root)
    frozen_manifest = json.loads(
        Path(config.frozen_index_manifest_path).read_text("utf-8")
    )
    relative_paths = [
        entry["relative_path"] for entry in frozen_manifest.get("corpus_entries", [])
    ]
    if len(relative_paths) != config.corpus_file_count:
        raise ValueError("冻结索引 corpus_entries 数量与配置不一致")
    corpus = ExperimentCorpus.build(str(corpus_path), relative_paths)
    basename_map = load_corpus(str(corpus_path), relative_paths)

    generation_cases = load_generation_cases(config.dev_jsonl_path)
    if len(generation_cases) != config.dev_case_count:
        raise ValueError(
            f"Dev case 数 {len(generation_cases)} 与配置 {config.dev_case_count} 不一致"
        )

    run_dir = Path(config.output_dir)
    if run_dir.exists():
        raise FileExistsError(f"输出目录已存在，禁止覆盖: {run_dir}")
    run_dir.mkdir(parents=True)

    workspace = run_dir.parent / "workspaces" / config.run_id
    index = build_shared_index(
        str(corpus_path), relative_paths, str(workspace / "vector_store")
    )
    index_manifest = dict(index.build_manifest)
    index_manifest["index_sha256"] = _sha256_bytes(_canonical_json(index_manifest))

    planner = OpenAICompatibleQueryPlanner(
        provider=config.planner_provider,
        model=config.planner_model,
        api_key=api_key,
        base_url="https://api.deepseek.com/v1",
    )
    generator = DeepSeekGenerator(
        api_key=api_key,
        model=config.generator_model,
        temperature=config.generator_temperature,
        timeout_seconds=config.generator_timeout,
        max_retries=config.generator_max_retries,
        max_total_tokens=4096,
        max_output_tokens=config.generator_max_tokens,
    )
    answer_port = E2EGroundedAnswerPort(
        generator,
        direct_model=config.planner_model,
        direct_api_key=api_key,
        direct_base_url="https://api.deepseek.com/v1",
    )
    retrieval_port = PipelineRetrievalAdapter(index.retriever)

    records = []
    cited_evidence_records = []
    for gcase in sorted(generation_cases, key=lambda c: c.case_id):
        sink: list[dict] = []
        runtime = AgentRuntime(
            planner=planner,
            retrieval_port=_RecordingRetrievalPort(retrieval_port, sink),
            answer_port=answer_port,
            budget=AgentRunBudget(
                max_retrieval_calls=config.max_retrieval_calls,
                max_evidence_items=config.max_evidence_items,
            ),
            merge_policy=config.merge_policy,
            merge_rrf_k=config.merge_rrf_k,
        )
        result = runtime.run(gcase.query, top_k=config.top_k)
        outcome = result.planner_outcome
        bundle = result.evidence_bundle
        evidence_items = list(bundle.items) if bundle is not None else []
        candidates = canonical_paths_from_documents(
            [d for entry in sink for d in entry["docs"]], basename_map
        )
        final_paths = canonical_paths_from_documents(evidence_items, basename_map)
        cited_ids = parse_citations(result.answer) if result.answer else set()
        cited_items = [
            item for item in evidence_items
            if _citation_int(item.citation_id) in cited_ids
        ]
        record = {
            "case_id": gcase.case_id,
            "query": gcase.query,
            "status": result.status,
            "error_code": result.error_code,
            "plan_id": outcome.plan.plan_id if outcome is not None else None,
            "plan": _redacted_plan(outcome.plan if outcome is not None else None),
            "route": (
                result.route_decision.route
                if result.route_decision is not None else None
            ),
            "retrieval_call_count": len(sink),
            "candidate_canonical_paths": candidates,
            "retrieved_canonical_paths": final_paths,
            "evidence_count": len(evidence_items),
            "fallback_used": (
                outcome.fallback_used if outcome is not None else None
            ),
            "failure_code": (
                outcome.failure_code if outcome is not None else None
            ),
            "answer": result.answer,
            "cited_citation_ids": sorted(cited_ids),
            "evidence_citation_ids": sorted(
                _citation_int(item.citation_id) for item in evidence_items
            ),
        }
        records.append(record)
        cited_evidence_records.append(
            {
                "case_id": gcase.case_id,
                "items": [
                    {
                        "citation_id": item.citation_id,
                        "source_name": item.source_name,
                        "canonical_path": basename_map[item.source_name],
                        "content": (item.content or "")[:300],
                    }
                    for item in cited_items
                ],
            }
        )

    write_text_atomic(
        run_dir / "run_config.json",
        _canonical_json(config.to_dict()).decode("utf-8"),
    )
    write_text_atomic(
        run_dir / "index_manifest.json",
        _canonical_json(index_manifest).decode("utf-8"),
    )
    case_lines = "\n".join(
        _canonical_json(r).decode("utf-8") for r in records
    )
    write_text_atomic(run_dir / "case_results.jsonl", case_lines + "\n")
    cited_lines = "\n".join(
        _canonical_json(r).decode("utf-8") for r in cited_evidence_records
    )
    write_text_atomic(run_dir / "cited_evidence.jsonl", cited_lines + "\n")
    for f in ("run_config.json", "index_manifest.json", "case_results.jsonl",
              "cited_evidence.jsonl"):
        assert_no_secrets((run_dir / f).read_text("utf-8"))
    return {
        "run_id": config.run_id,
        "case_count": len(records),
        "status_counts": _count_statuses(records),
    }


def _count_statuses(records) -> dict:
    counts: dict[str, int] = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def load_run_case_results(run_dir: Path) -> list[dict]:
    records = []
    with (run_dir / "case_results.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_run_cited_evidence(run_dir: Path) -> dict:
    out: dict[str, list] = {}
    with (run_dir / "cited_evidence.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                out[rec["case_id"]] = rec["items"]
    return out


def should_call_judge(record: dict, has_obligations: bool) -> bool:
    """Judge 只在生成完成、有答案且有 Gold obligation 的 case 上调用。"""
    return (
        has_obligations
        and record.get("status") == "completed"
        and bool(record.get("answer"))
    )


def run_e2e_evaluation(
    config: Gate3E2EConfig,
    run_dir: Path,
    *,
    judge_client=None,
) -> dict:
    """Evaluation stage：离线读取 Dev Gold + 持久化生成结果，跑确定性指标
    与 LLM Judge，聚合 answer 指标并写 Artifact。"""
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量")

    records = load_run_case_results(run_dir)
    cited_map = load_run_cited_evidence(run_dir)
    if len(records) != config.dev_case_count:
        raise ValueError("case_results 数量与配置不一致")

    corpus_path = Path(config.corpus_root)
    frozen_manifest = json.loads(
        Path(config.frozen_index_manifest_path).read_text("utf-8")
    )
    relative_paths = [
        entry["relative_path"] for entry in frozen_manifest.get("corpus_entries", [])
    ]
    corpus = ExperimentCorpus.build(str(corpus_path), relative_paths)
    dev_set = Gate3EvaluationSet.load_jsonl(config.dev_jsonl_path, corpus)
    case_by_id = {c.case_id: c for c in dev_set.cases}

    judge = AnswerJudge(config=config, api_key=api_key, client=judge_client)

    judgments = []
    for rec in records:
        case = case_by_id[rec["case_id"]]
        gold_obligations = [
            {"obligation_id": o.obligation_id, "description": o.description}
            for o in case.evidence_obligations
        ]
        cited = cited_map.get(rec["case_id"], [])
        # 零 obligation（unanswerable/no_retrieval/direct）的 case 不调 Judge：
        # 不允许凭空造 obligation，单独上报。
        if should_call_judge(rec, bool(case.evidence_obligations)):
            judge_result = judge.judge(
                rec["query"], rec["answer"], cited, gold_obligations
            )
        else:
            judge_result = {"judge_status": "not_generated"}
        judgments.append(
            {
                "case_id": rec["case_id"],
                "judge_input": {
                    "query": rec["query"],
                    "answer": rec.get("answer"),
                    "cited_evidence": cited,
                    "gold_obligations": gold_obligations,
                },
                "judge_output": judge_result,
            }
        )

    deterministic = compute_deterministic_metrics(records, dev_set, case_by_id)
    answer_metrics = compute_answer_metrics(records, judgments, dev_set, case_by_id)

    metrics = {
        "schema_version": GATE3_E2E_METRICS_SCHEMA_VERSION,
        "deterministic": deterministic,
        "answer": answer_metrics,
        "answerable_case_count": sum(
            1 for c in dev_set.cases if c.answerability == "answerable"
        ),
        "case_count": len(records),
    }

    comparison = build_e2e_comparison_report(metrics)

    write_text_atomic(
        run_dir / "answer_judgments.jsonl",
        "\n".join(_canonical_json(j).decode("utf-8") for j in judgments) + "\n",
    )
    write_text_atomic(
        run_dir / "metrics.json", _canonical_json(metrics).decode("utf-8")
    )
    write_text_atomic(run_dir / "comparison_report.md", comparison)
    write_text_atomic(
        run_dir / "result.json",
        _canonical_json(
            {
                "schema_version": GATE3_E2E_RESULT_SCHEMA_VERSION,
                "run_id": config.run_id,
                "config": config.to_dict(),
                "metrics": metrics,
            }
        ).decode("utf-8"),
    )
    for f in ("answer_judgments.jsonl", "metrics.json", "comparison_report.md",
              "result.json"):
        assert_no_secrets((run_dir / f).read_text("utf-8"))
    return metrics


def compute_deterministic_metrics(records, dev_set, case_by_id) -> dict:
    status_counts = _count_statuses(records)
    fallback = sum(1 for r in records if r.get("fallback_used"))
    schema_failure = sum(
        1 for r in records if r.get("failure_code") not in (None, "PLANNER_FALLBACK")
    )
    total_calls = sum(r.get("retrieval_call_count", 0) for r in records)
    total_evidence = sum(r.get("evidence_count", 0) for r in records)

    citation_agg = {
        "invalid_citation_total": 0,
        "uncited_evidence_total": 0,
        "citation_valid_case_count": 0,
        "evaluable_case_count": 0,
    }
    for r in records:
        if r.get("status") != "completed" or not r.get("answer"):
            continue
        cit = evaluate_citations(
            r.get("answer"), r.get("evidence_citation_ids", [])
        )
        citation_agg["invalid_citation_total"] += cit["invalid_count"]
        citation_agg["uncited_evidence_total"] += cit["uncited_evidence_count"]
        citation_agg["evaluable_case_count"] += 1
        if cit["invalid_count"] == 0:
            citation_agg["citation_valid_case_count"] += 1

    doc = compute_document_metrics(
        {r["case_id"]: r for r in records}, dev_set.cases
    )
    obl = compute_obligation_metrics(
        {r["case_id"]: r for r in records}, dev_set.cases,
        candidate_key="retrieved_canonical_paths",
    )
    return {
        "status_counts": status_counts,
        "planner_fallback_count": fallback,
        "planner_schema_failure_count": schema_failure,
        "retrieval_call_count_total": total_calls,
        "evidence_count_total": total_evidence,
        "document": doc,
        "obligation": obl,
        "citation": citation_agg,
    }


def compute_answer_metrics(records, judgments, dev_set, case_by_id) -> dict:
    """核心 Answer 指标（Judge + citation 确定性校验）。"""
    by_case = {r["case_id"]: r for r in records}
    by_judge = {j["case_id"]: j.get("judge_output", {}) for j in judgments}

    answerable = [c for c in dev_set.cases if c.answerability == "answerable"]
    total_obligations = 0
    covered_obligations = 0
    full_coverage_cases = 0
    unsupported_cases = 0
    pass_cases = 0
    invalid_judge_cases = 0
    no_answer_cases = 0
    citation_valid_cases = 0
    citation_valid_denom = 0
    for case in answerable:
        rec = by_case[case.case_id]
        j = by_judge.get(case.case_id, {})
        if not case.evidence_obligations:
            zero_obligation_cases += 1
            continue
        total_obligations += len(case.evidence_obligations)
        has_answer = rec.get("status") == "completed" and bool(rec.get("answer"))
        if not has_answer:
            no_answer_cases += 1
        coverage = j.get("obligation_coverage", {})
        covered = sum(1 for o in case.evidence_obligations
                      if coverage.get(o.obligation_id) == JUDGE_COVERED)
        covered_obligations += covered
        all_covered = covered == len(case.evidence_obligations)
        if all_covered:
            full_coverage_cases += 1
        unsupported = bool(j.get("unsupported_material_claims"))
        if unsupported:
            unsupported_cases += 1
        if j.get("judge_status") == "invalid":
            invalid_judge_cases += 1
        # citation 有效性只对实际产出答案的 case 计分母；no-answer 单独上报。
        citation_ok = False
        if has_answer:
            citation_valid_denom += 1
            cit = evaluate_citations(
                rec.get("answer"), rec.get("evidence_citation_ids", [])
            )
            if cit["invalid_count"] == 0:
                citation_valid_cases += 1
                citation_ok = True
        if all_covered and citation_ok and not unsupported:
            pass_cases += 1

    non_answerable = [c for c in dev_set.cases if c.answerability != "answerable"]
    return {
        "answer_obligation_covered": covered_obligations,
        "answer_obligation_total": total_obligations,
        "answer_obligation_coverage_rate": _safe_rate(
            covered_obligations, total_obligations),
        "answer_full_coverage_case_count": full_coverage_cases,
        "answerable_case_count": len(answerable),
        "answer_full_coverage_rate": _safe_rate(full_coverage_cases, len(answerable)),
        "citation_valid_case_count": citation_valid_cases,
        "citation_valid_denominator": citation_valid_denom,
        "citation_valid_case_rate": _safe_rate(
            citation_valid_cases, citation_valid_denom),
        "unsupported_claim_case_count": unsupported_cases,
        "answer_pass_case_count": pass_cases,
        "answer_pass_rate": _safe_rate(pass_cases, len(answerable)),
        "invalid_judge_case_count": invalid_judge_cases,
        "no_answer_case_count": no_answer_cases,
        "non_answerable_case_count": len(non_answerable),
        "non_answerable_cases": sorted(c.case_id for c in non_answerable),
    }


def build_e2e_comparison_report(metrics: dict) -> str:
    d = metrics["deterministic"]
    a = metrics["answer"]
    lines = ["# G3-E2E-07A 真实 E2E 答案评测报告（Dev）", ""]
    lines.append("## Run 概览")
    lines.append("")
    lines.append(
        f"- case_count={metrics['case_count']}；answerable="
        f"{a['answerable_case_count']}；non_answerable="
        f"{a['non_answerable_case_count']}（{', '.join(a['non_answerable_cases']) or '—'}）"
    )
    lines.append(f"- status 分布：{d['status_counts']}")
    lines.append(f"- planner fallback={d['planner_fallback_count']}；"
                 f"schema failure={d['planner_schema_failure_count']}")
    lines.append(f"- retrieval calls={d['retrieval_call_count_total']}；"
                 f"evidence total={d['evidence_count_total']}")
    lines.append("")
    lines.append("## 核心 Answer 指标")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(
        f"| answer_obligation 覆盖 | {a['answer_obligation_covered']}/"
        f"{a['answer_obligation_total']} = {a['answer_obligation_coverage_rate']:.4f} |"
    )
    lines.append(
        f"| answer full coverage | {a['answer_full_coverage_case_count']}/"
        f"{a['answerable_case_count']} = {a['answer_full_coverage_rate']:.4f} |"
    )
    lines.append(
        f"| citation valid case | {a['citation_valid_case_count']}/"
        f"{a['answerable_case_count']} = {a['citation_valid_case_rate']:.4f} |"
    )
    lines.append(f"| unsupported claim case | {a['unsupported_claim_case_count']} |")
    lines.append(
        f"| answer pass case | {a['answer_pass_case_count']}/"
        f"{a['answerable_case_count']} = {a['answer_pass_rate']:.4f} |"
    )
    lines.append(f"| invalid judge | {a['invalid_judge_case_count']} |")
    lines.append(f"| no-answer | {a['no_answer_case_count']} |")
    lines.append("")
    lines.append("## 检索（确定性）层")
    lines.append("")
    lines.append(
        f"- obligation 覆盖（retrieval）：{d['obligation']['obligation_covered']}"
        f"/{d['obligation']['obligation_total']} = "
        f"{d['obligation']['obligation_coverage_rate']:.4f}"
    )
    lines.append(
        f"- document Hit@5={d['document']['hit_at_5']:.4f}，"
        f"Recall@5={d['document']['recall_at_5']:.4f}"
    )
    lines.append("")
    lines.append("> 说明：本报告为 Dev-only 真实 E2E（Real Planner + Real Generator + "
                 "Citation）。LLM Judge 是辅助评测，不等同于人工 Ground Truth；"
                 "若 Generator 与 Judge 使用同模型，存在 same-model bias。"
                 "未运行 Holdout。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# R1：离线 Evaluation Provenance Repair（纯离线，不调用任何 LLM/检索/embedding）
# ---------------------------------------------------------------------------

GATE3_E2E_REPAIR_SCHEMA_VERSION = "gate3_e2e_repair_v1"


@dataclass(frozen=True)
class E2ERepairConfig:
    """离线 evaluation repair 身份：双来源绑定（generation + evaluation）。

    repair_id 绑定：parent_generation_run_id / generation_source_commit /
    evaluation_source_commit / 三个上游 Artifact SHA / dev/freeze 身份 /
    judge prompt SHA / evaluation schema。
    """

    schema_version: str = GATE3_E2E_REPAIR_SCHEMA_VERSION
    evaluation_schema_version: str = GATE3_E2E_METRICS_SCHEMA_VERSION
    parent_generation_run_id: str = ""
    generation_source_commit: str = ""
    evaluation_source_commit: str = ""
    case_results_sha256: str = ""
    cited_evidence_sha256: str = ""
    source_answer_judgments_sha256: str = ""
    dev_evaluation_set_id: str = ""
    dev_jsonl_sha256: str = ""
    gate3_dataset_freeze_id: str = ""
    judge_prompt_sha256: str = ""
    # Judge provenance（复用既有判断，记录其配置）
    judge_provider: str = "deepseek"
    judge_model: str = "deepseek-chat"
    judge_temperature: float = 0.0
    judge_timeout: float = 60.0
    judge_max_tokens: int = 800
    judge_max_retries: int = 2
    # 执行路径（不进 repair_id）
    parent_run_dir: str = ""
    output_dir: str = ""

    def __post_init__(self) -> None:
        _check_hex(self.parent_generation_run_id, 12, "parent_generation_run_id")
        _check_hex(self.generation_source_commit, 40, "generation_source_commit")
        _check_hex(self.evaluation_source_commit, 40, "evaluation_source_commit")
        for name in ("case_results_sha256", "cited_evidence_sha256",
                     "source_answer_judgments_sha256", "dev_jsonl_sha256",
                     "judge_prompt_sha256"):
            _check_hex(getattr(self, name), 64, name)
        _check_hex(self.dev_evaluation_set_id, 12, "dev_evaluation_set_id")
        _check_hex(self.gate3_dataset_freeze_id, 12, "gate3_dataset_freeze_id")
        _check_nonempty_no_ws(self.judge_model, "judge_model")
        for label in ("evaluation_schema_version", "schema_version"):
            _check_nonempty_no_ws(getattr(self, label), label)

    def identity_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "evaluation_schema_version": self.evaluation_schema_version,
            "parent_generation_run_id": self.parent_generation_run_id,
            "generation_source_commit": self.generation_source_commit,
            "evaluation_source_commit": self.evaluation_source_commit,
            "case_results_sha256": self.case_results_sha256,
            "cited_evidence_sha256": self.cited_evidence_sha256,
            "source_answer_judgments_sha256": self.source_answer_judgments_sha256,
            "dev_evaluation_set_id": self.dev_evaluation_set_id,
            "dev_jsonl_sha256": self.dev_jsonl_sha256,
            "gate3_dataset_freeze_id": self.gate3_dataset_freeze_id,
            "judge_prompt_sha256": self.judge_prompt_sha256,
        }

    @property
    def repair_id(self) -> str:
        return _sha256_bytes(_canonical_json(self.identity_payload()))[:12]

    def to_dict(self) -> dict:
        payload = dict(self.identity_payload())
        payload["repair_id"] = self.repair_id
        payload["judge_provider"] = self.judge_provider
        payload["judge_model"] = self.judge_model
        payload["judge_temperature"] = self.judge_temperature
        payload["judge_timeout"] = self.judge_timeout
        payload["judge_max_tokens"] = self.judge_max_tokens
        payload["judge_max_retries"] = self.judge_max_retries
        payload["parent_run_dir"] = "set" if self.parent_run_dir else ""
        payload["output_dir"] = "set" if self.output_dir else ""
        return payload


def build_repair_config(
    parent_run_dir: Path,
    *,
    evaluation_source_commit: str,
    judge_model: str,
) -> E2ERepairConfig:
    """从父 run 持久化 Artifact 构建 repair 配置（不调用任何 LLM/检索）。"""
    parent = Path(parent_run_dir)
    run_config_path = parent / "run_config.json"
    for required in ("run_config.json", "case_results.jsonl",
                     "cited_evidence.jsonl", "answer_judgments.jsonl"):
        if not (parent / required).is_file():
            raise FileNotFoundError(f"父 run 缺少 {required}: {parent}")
    pc = json.loads(run_config_path.read_text("utf-8"))
    if pc.get("judge_prompt_sha256") != GATE3_ANSWER_JUDGE_PROMPT_SHA256:
        raise ValueError("父 run judge_prompt_sha256 与冻结 judge prompt 不一致")
    return E2ERepairConfig(
        parent_generation_run_id=pc["run_id"],
        generation_source_commit=pc["source_commit"],
        evaluation_source_commit=evaluation_source_commit,
        case_results_sha256=_sha256_file(parent / "case_results.jsonl"),
        cited_evidence_sha256=_sha256_file(parent / "cited_evidence.jsonl"),
        source_answer_judgments_sha256=_sha256_file(
            parent / "answer_judgments.jsonl"),
        dev_evaluation_set_id=pc["dev_evaluation_set_id"],
        dev_jsonl_sha256=pc["dev_jsonl_sha256"],
        gate3_dataset_freeze_id=pc["gate3_dataset_freeze_id"],
        judge_prompt_sha256=GATE3_ANSWER_JUDGE_PROMPT_SHA256,
        judge_model=judge_model,
        parent_run_dir=str(parent),
    )


def verify_reusable_judgments(
    records, cited_map, old_judgments, dev_set, expected_judge_prompt_sha: str
):
    """对每个可复用 Judge 判断做输入一致性校验；任何 mismatch 即失败。

    可复用条件：obligation>0 且 completed 且有 answer 且 judge_status=ok。
    校验：case_id 对齐、query 对齐、answer 对齐、cited evidence 对齐、
    Gold obligation IDs 对齐、judge prompt SHA 对齐。
    返回 (reusable 列表, mismatch 列表)；mismatch 非空时必须停止。
    """
    case_by_id = {c.case_id: c for c in dev_set.cases}
    old_by_case = {j["case_id"]: j for j in old_judgments}
    reusable = []
    mismatches = []
    for rec in records:
        case = case_by_id[rec["case_id"]]
        if not case.evidence_obligations:
            continue  # 零 obligation → 不要求 Judge
        if not (rec.get("status") == "completed" and rec.get("answer")):
            continue  # 未生成
        j = old_by_case.get(rec["case_id"])
        if j is None or j.get("judge_output", {}).get("judge_status") != "ok":
            mismatches.append((rec["case_id"], "missing_or_not_ok"))
            continue
        stored = j.get("judge_input", {})
        expected = {
            "query": rec["query"],
            "answer": rec["answer"],
            "cited_evidence": cited_map.get(rec["case_id"], []),
            "gold_obligations": [
                {"obligation_id": o.obligation_id, "description": o.description}
                for o in case.evidence_obligations
            ],
        }
        stored_subset = {
            k: stored.get(k) for k in ("query", "answer", "cited_evidence",
                                       "gold_obligations")
        }
        if _canonical_json(stored_subset) != _canonical_json(expected):
            mismatches.append((rec["case_id"], "input_mismatch"))
            continue
        if expected_judge_prompt_sha != GATE3_ANSWER_JUDGE_PROMPT_SHA256:
            mismatches.append((rec["case_id"], "judge_prompt_sha_mismatch"))
            continue
        reusable.append(j)
    return reusable, mismatches


def build_corrected_judgments(records, reusable_by_case, dev_set) -> list[dict]:
    """构造修正后的 answer_judgments：

    零 obligation case → judge_not_required (reason=zero_obligation)；
    可复用判断 → 原样；其余（GENERATION_FAILED 等）→ not_generated。
    零 obligation 的判断不得进入任何指标输入。
    """
    case_by_id = {c.case_id: c for c in dev_set.cases}
    corrected = []
    for rec in sorted(records, key=lambda r: r["case_id"]):
        case = case_by_id[rec["case_id"]]
        if not case.evidence_obligations:
            corrected.append(
                {"case_id": rec["case_id"],
                 "judge_output": {"judge_status": "not_required",
                                  "reason": "zero_obligation"}}
            )
        elif rec["case_id"] in reusable_by_case:
            corrected.append(
                {"case_id": rec["case_id"],
                 "judge_output": reusable_by_case[rec["case_id"]]["judge_output"]}
            )
        else:
            corrected.append(
                {"case_id": rec["case_id"],
                 "judge_output": {"judge_status": "not_generated"}}
            )
    return corrected


def reevaluate_existing_e2e_run(
    parent_run_dir: Path,
    output_root: Path,
    *,
    evaluation_source_commit: str,
    dev_jsonl_path: str,
    frozen_index_manifest_path: str,
    corpus_root: str,
    judge_model: str = "deepseek-chat",
) -> dict:
    """纯离线 evaluation repair：复用父 run 持久化生成/Judge 结果，用当前
    evaluator 重算指标。禁止任何 LLM/embedding/retrieval 调用；不修改父 run。"""
    repair = build_repair_config(
        parent_run_dir, evaluation_source_commit=evaluation_source_commit,
        judge_model=judge_model,
    )
    if _sha256_file(Path(dev_jsonl_path)) != repair.dev_jsonl_sha256:
        raise ValueError("dev jsonl 实际 SHA 与父 run 记录不一致")
    frozen = json.loads(Path(frozen_index_manifest_path).read_text("utf-8"))
    relative_paths = [
        entry["relative_path"] for entry in frozen.get("corpus_entries", [])
    ]
    corpus = ExperimentCorpus.build(corpus_root, relative_paths)
    dev_set = Gate3EvaluationSet.load_jsonl(dev_jsonl_path, corpus)
    case_by_id = {c.case_id: c for c in dev_set.cases}

    records = load_run_case_results(Path(parent_run_dir))
    cited_map = load_run_cited_evidence(Path(parent_run_dir))
    old_judgments = [
        json.loads(l) for l in
        (Path(parent_run_dir) / "answer_judgments.jsonl")
        .read_text("utf-8").splitlines() if l.strip()
    ]
    parent_pc = json.loads(
        (Path(parent_run_dir) / "run_config.json").read_text("utf-8")
    )
    if len(records) != parent_pc["dev_case_count"]:
        raise ValueError("父 run case_results 数量与 dev 不一致")

    reusable, mismatches = verify_reusable_judgments(
        records, cited_map, old_judgments, dev_set,
        GATE3_ANSWER_JUDGE_PROMPT_SHA256,
    )
    if mismatches:
        raise RuntimeError(
            "Judge 输入一致性校验失败，禁止自动重跑 Judge："
            + repr(mismatches)
        )
    reusable_by_case = {j["case_id"]: j for j in reusable}
    corrected = build_corrected_judgments(records, reusable_by_case, dev_set)

    det = compute_deterministic_metrics(records, dev_set, case_by_id)
    ans = compute_answer_metrics(records, corrected, dev_set, case_by_id)
    metrics = {
        "schema_version": GATE3_E2E_METRICS_SCHEMA_VERSION,
        "deterministic": det,
        "answer": ans,
        "answerable_case_count": ans["answerable_case_count"],
        "case_count": len(records),
    }

    output_dir = Path(output_root) / repair.repair_id
    if output_dir.exists():
        raise FileExistsError(f"repair 输出目录已存在，禁止覆盖: {output_dir}")
    output_dir.mkdir(parents=True)

    parent = Path(parent_run_dir)
    source_artifacts = {
        "parent_run_dir": str(parent),
        "parent_run_id": repair.parent_generation_run_id,
        "generation_source_commit": repair.generation_source_commit,
        "case_results_sha256": repair.case_results_sha256,
        "cited_evidence_sha256": repair.cited_evidence_sha256,
        "source_answer_judgments_sha256": repair.source_answer_judgments_sha256,
        "run_config_sha256": _sha256_file(parent / "run_config.json"),
    }
    write_text_atomic(
        output_dir / "repair_config.json",
        _canonical_json(repair.to_dict()).decode("utf-8"),
    )
    write_text_atomic(
        output_dir / "source_artifacts.json",
        _canonical_json(source_artifacts).decode("utf-8"),
    )
    write_text_atomic(
        output_dir / "answer_judgments.jsonl",
        "\n".join(_canonical_json(j).decode("utf-8") for j in corrected) + "\n",
    )
    write_text_atomic(
        output_dir / "metrics.json", _canonical_json(metrics).decode("utf-8")
    )
    write_text_atomic(
        output_dir / "comparison_report.md",
        build_repair_report(
            repair, metrics, reusable_count=len(reusable),
            input_mismatch=len(mismatches),
        ),
    )
    write_text_atomic(
        output_dir / "result.json",
        _canonical_json(
            {
                "schema_version": GATE3_E2E_RESULT_SCHEMA_VERSION,
                "repair_id": repair.repair_id,
                "repair_config": repair.to_dict(),
                "source_artifacts": source_artifacts,
                "metrics": metrics,
            }
        ).decode("utf-8"),
    )
    for f in ("repair_config.json", "source_artifacts.json",
              "answer_judgments.jsonl", "metrics.json",
              "comparison_report.md", "result.json"):
        assert_no_secrets((output_dir / f).read_text("utf-8"))
    return {
        "repair_id": repair.repair_id,
        "reusable_judgments": len(reusable),
        "input_mismatch": len(mismatches),
        "metrics": metrics,
    }


def build_repair_report(repair, metrics, *, reusable_count, input_mismatch) -> str:
    d = metrics["deterministic"]
    a = metrics["answer"]
    lines = ["# G3-E2E-07A-R1 离线 Evaluation Provenance Repair（Dev）", ""]
    lines.append(
        "> **R1 is an offline evaluation provenance repair — NOT a "
        "performance reproduction run.** 不调用任何 LLM；不重跑 Planner/"
        "Retrieval/Generator/Judge/embedding；不改 prompt/model；不改父 run。"
    )
    lines.append("")
    lines.append("## 父 run 4172f6cc1d6f 身份")
    lines.append("")
    lines.append("- **generation_valid = true**：generation/retrieval 观测有效")
    lines.append("- **final_evaluation_superseded = true**")
    lines.append(
        "- **superseded_reason** = post-run evaluator correctness fixes "
        "changed zero-obligation Judge gating and citation denominator "
        "after recorded generation source commit"
    )
    lines.append(
        "- 4 个 GENERATION_FAILED / live Planner drift / retrieval 35/44 "
        "为真实发生行为，原样保留，不被抹掉"
    )
    lines.append("")
    lines.append("## 双来源绑定")
    lines.append("")
    lines.append(f"- parent_generation_run_id = {repair.parent_generation_run_id}")
    lines.append(f"- generation_source_commit = {repair.generation_source_commit}")
    lines.append(f"- evaluation_source_commit = {repair.evaluation_source_commit}")
    lines.append(f"- repair_id = {repair.repair_id}")
    lines.append("")
    lines.append("## Online observations inherited unchanged")
    lines.append("")
    lines.append(f"- Planner calls = 24；retrieval calls = "
                 f"{d['retrieval_call_count_total']}")
    lines.append(f"- status 分布 = {d['status_counts']}（4 个 GENERATION_FAILED "
                 "原样保留，未重跑生成）")
    lines.append(f"- planner fallback = {d['planner_fallback_count']}（均 "
                 "PLAN_INVALID_SCHEMA → single_retrieval）")
    lines.append(
        f"- retrieval obligation 覆盖 = {d['obligation']['obligation_covered']}/"
        f"{d['obligation']['obligation_total']} = "
        f"{d['obligation']['obligation_coverage_rate']:.4f}"
    )
    lines.append(
        "- live Planner drift / answers / citations 全部继承自父 run，未重算"
    )
    lines.append("")
    lines.append("## Offline metrics recomputed（修正后 evaluator）")
    lines.append("")
    lines.append(f"- reusable judgments = {reusable_count}/16；"
                 f"input mismatch = {input_mismatch}")
    lines.append(
        "- Judge gating：零 obligation case judge_not_required "
        "(reason=zero_obligation)，不进任何分母"
    )
    lines.append(
        "- citation denominator 只含实际生成且可评价的 answerable case"
    )
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(
        f"| answer_obligation 覆盖 | {a['answer_obligation_covered']}/"
        f"{a['answer_obligation_total']} = {a['answer_obligation_coverage_rate']:.4f} |"
    )
    lines.append(
        f"| answer full coverage | {a['answer_full_coverage_case_count']}/"
        f"{a['answerable_case_count']} = {a['answer_full_coverage_rate']:.4f} |"
    )
    lines.append(
        f"| citation valid | {a['citation_valid_case_count']}/"
        f"{a['citation_valid_denominator']}（可评价） = "
        f"{a['citation_valid_case_rate']:.4f} |"
    )
    lines.append(f"| unsupported claim case | {a['unsupported_claim_case_count']} |")
    lines.append(f"| invalid judge | {a['invalid_judge_case_count']} |")
    lines.append(f"| no-answer | {a['no_answer_case_count']} |")
    lines.append(
        f"| answer pass | {a['answer_pass_case_count']}/"
        f"{a['answerable_case_count']} = {a['answer_pass_rate']:.4f} |"
    )
    lines.append("")
    lines.append("## 4172 → R1 对照（reproducibility repair，非性能 A/B）")
    lines.append("")
    lines.append("| 指标 | 4172（在线，初报） | R1（离线 repair 重算） |")
    lines.append("|---|---|---|")
    lines.append("| generation failures | 4 | 4（继承，未重跑） |")
    lines.append(
        f"| retrieval obligation | {d['obligation']['obligation_covered']}/44 | "
        f"{d['obligation']['obligation_covered']}/44（继承） |"
    )
    lines.append(
        f"| answer obligation | 21/44 | {a['answer_obligation_covered']}/44（重算） |"
    )
    lines.append(
        f"| answer pass | 8/20 | {a['answer_pass_case_count']}/20（重算） |"
    )
    lines.append(
        f"| citation valid | 16/20* | {a['citation_valid_case_count']}（重算，"
        "denominator 修正） |"
    )
    lines.append("")
    lines.append(
        "* 4172 初报 citation_valid 分母曾含 4 个 no-answer；R1 修正分母只计"
        "实际生成且可评价的 answerable case。"
    )
    lines.append("")
    lines.append(
        "> LLM 非确定性说明：本 repair 为纯离线，未调用任何 LLM；指标全部由"
        "持久化 per-case/judgment 用修正后 evaluator 独立重算。"
    )
    return "\n".join(lines)
