"""G3-HOLDOUT-09A：一次性、Freeze-bound 的 Holdout execution harness。

本模块建立 Holdout 执行基础设施：独立强类型身份（Gate3HoldoutConfig）、
Freeze-bound 配置来源（唯一来自 gate3_system_freeze.json，fail-fast 校验）、
一次性 attempt ledger 状态机、preflight/dry-run（09A 只允许该模式）。

09A 绝对不读取 gate3/sealed/、不调用任何 LLM、不真正运行 Holdout；测试只用
tmp_path / synthetic fixture / 公开 Dev fixture。实际执行（09B）在授权后才会
原子创建 attempt 并访问 sealed。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from evaluation.gate3.adaptive_dev import (
    _canonical_json,
    _check_hex,
    _check_nonempty_no_ws,
    _sha256_bytes,
    check_git_tracked_clean,
    write_text_atomic,
)
from evaluation.gate3.e2e import GATE3_E2E_METRICS_SCHEMA_VERSION

GATE3_HOLDOUT_SCHEMA_VERSION = "gate3_holdout_run_v1"
HOLDOUT_ATTEMPT_LEDGER_SCHEMA = "holdout_attempt_ledger_v1"

# Freeze-bound 期望常量（来自已审计 gate3_system_freeze.json）。
EXPECTED_FREEZE_ID = "2ec11a69b173"
EXPECTED_FROZEN_BASELINE = "fed9d15b950fe543d1afc99a2a21a5ad5d299320"
EXPECTED_GATE3_DATASET_FREEZE_ID = "257fa0d0a6d6"
EXPECTED_HOLDOUT_EVALUATION_SET_ID = "79a6bc0814a3"
EXPECTED_HOLDOUT_CASE_COUNT = 12

# attempt 状态：prepared / running / completed / invalid_infrastructure / failed_system。
HOLDOUT_ATTEMPT_STATUSES = (
    "prepared", "running", "completed",
    "invalid_infrastructure", "failed_system",
)
# 一旦出现这些状态即禁止第二次开始。
_ACTIVE_BLOCKING_STATUSES = ("running", "completed", "failed_system")
# invalid_infrastructure：不得自动重跑，必须 Reviewer audit 后显式授权/拒绝替代 attempt。
_REVIEWER_GATED_STATUS = "invalid_infrastructure"

# Runner 禁止提供的性能 override 参数名（必须在 CLI 中缺失）。
FORBIDDEN_OVERRIDE_ARGS = (
    "--planner-model", "--generator-model", "--judge-model",
    "--temperature", "--top-k", "--merge-policy", "--merge-rrf-k", "--max-evidence",
)


def _canonical(obj):
    return _canonical_json(obj)


@dataclass(frozen=True)
class Gate3HoldoutConfig:
    """Holdout 独立强类型身份；绑定 Freeze 与执行来源。

    holdout_run_id 绑定：freeze_id / dataset freeze id / holdout evaluation_set_id /
    holdout_case_count / actual_execution_source_commit / 全部 frozen runtime &
    Planner/Generator/Judge 配置。绝不使用 dev_evaluation_set_id 伪装 Holdout。
    """

    schema_version: str = GATE3_HOLDOUT_SCHEMA_VERSION
    evaluation_schema_version: str = GATE3_E2E_METRICS_SCHEMA_VERSION
    gate3_system_freeze_id: str = ""
    gate3_dataset_freeze_id: str = ""
    holdout_evaluation_set_id: str = ""
    holdout_case_count: int = 0
    actual_execution_source_commit: str = ""
    # 全部继承自 gate3_system_freeze.json（唯一配置来源）
    retrieval: dict = field(default_factory=dict)
    planner: dict = field(default_factory=dict)
    generator: dict = field(default_factory=dict)
    judge: dict = field(default_factory=dict)
    # 执行位置（不进身份）
    holdout_jsonl_path: str = ""
    private_manifest_path: str = ""
    frozen_index_manifest_path: str = ""
    corpus_root: str = ""
    output_root: str = ""

    def __post_init__(self) -> None:
        _check_hex(self.gate3_system_freeze_id, 12, "gate3_system_freeze_id")
        _check_hex(self.gate3_dataset_freeze_id, 12, "gate3_dataset_freeze_id")
        _check_hex(self.holdout_evaluation_set_id, 12, "holdout_evaluation_set_id")
        _check_hex(self.actual_execution_source_commit, 40,
                   "actual_execution_source_commit")
        if (type(self.holdout_case_count) is not int
                or isinstance(self.holdout_case_count, bool)
                or self.holdout_case_count <= 0):
            raise ValueError("holdout_case_count 必须是严格正整数")
        for label in ("evaluation_schema_version", "schema_version"):
            _check_nonempty_no_ws(getattr(self, label), label)
        for section in ("retrieval", "planner", "generator", "judge"):
            if not isinstance(getattr(self, section), dict) or not getattr(
                self, section
            ):
                raise ValueError(f"{section} frozen config 必须是非空 object")

    def identity_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "evaluation_schema_version": self.evaluation_schema_version,
            "gate3_system_freeze_id": self.gate3_system_freeze_id,
            "gate3_dataset_freeze_id": self.gate3_dataset_freeze_id,
            "holdout_evaluation_set_id": self.holdout_evaluation_set_id,
            "holdout_case_count": self.holdout_case_count,
            "actual_execution_source_commit": self.actual_execution_source_commit,
            "retrieval": self.retrieval,
            "planner": self.planner,
            "generator": self.generator,
            "judge": self.judge,
        }

    @property
    def holdout_run_id(self) -> str:
        return _sha256_bytes(_canonical(self.identity_payload()))[:12]

    def to_dict(self) -> dict:
        payload = dict(self.identity_payload())
        payload["holdout_run_id"] = self.holdout_run_id
        for name in ("holdout_jsonl_path", "private_manifest_path",
                     "frozen_index_manifest_path", "corpus_root", "output_root"):
            payload[name] = "set" if getattr(self, name) else ""
        return payload


def _validate_freeze_json(freeze: dict) -> dict:
    """验证 Freeze JSON 身份与 frozen knobs；任一不一致 fail-fast。

    不做任何 sealed 访问；只读公开 freeze metadata。
    """
    if freeze.get("schema_version") != "gate3_system_freeze_v1":
        raise ValueError("freeze schema_version 必须是 gate3_system_freeze_v1")
    if freeze.get("gate3_system_freeze_id") != EXPECTED_FREEZE_ID:
        raise ValueError(
            f"gate3_system_freeze_id 必须是 {EXPECTED_FREEZE_ID}，"
            f"实际 {freeze.get('gate3_system_freeze_id')}"
        )
    if freeze.get("frozen_code_baseline_commit") != EXPECTED_FROZEN_BASELINE:
        raise ValueError(
            f"frozen_code_baseline_commit 必须是 {EXPECTED_FROZEN_BASELINE}，"
            f"实际 {freeze.get('frozen_code_baseline_commit')}"
        )
    dataset = freeze.get("dataset_identities")
    if not isinstance(dataset, dict):
        raise ValueError("freeze dataset_identities 缺失")
    if dataset.get("gate3_dataset_freeze_id") != EXPECTED_GATE3_DATASET_FREEZE_ID:
        raise ValueError(
            f"gate3_dataset_freeze_id 必须是 {EXPECTED_GATE3_DATASET_FREEZE_ID}"
        )
    if dataset.get("holdout_evaluation_set_id") != EXPECTED_HOLDOUT_EVALUATION_SET_ID:
        raise ValueError(
            f"holdout_evaluation_set_id 必须是 {EXPECTED_HOLDOUT_EVALUATION_SET_ID}"
        )
    # 重算 freeze_id（排除自指）确认 Freeze 文档未被篡改。
    recomputed = _sha256_bytes(_canonical(
        {k: v for k, v in freeze.items() if k != "gate3_system_freeze_id"}
    ))[:12]
    if recomputed != freeze["gate3_system_freeze_id"]:
        raise ValueError("gate3_system_freeze_id 与 canonical payload 重算不一致")
    for section in ("retrieval_runtime_config", "planner", "generator", "judge"):
        if not isinstance(freeze.get(section), dict) or not freeze.get(section):
            raise ValueError(f"freeze {section} 缺失或为空")
    return freeze


def build_holdout_config_from_freeze(
    freeze_json_path: str,
    *,
    actual_execution_source_commit: str,
    holdout_jsonl_path: str,
    private_manifest_path: str,
    frozen_index_manifest_path: str,
    corpus_root: str,
    output_root: str,
) -> Gate3HoldoutConfig:
    """gate3_system_freeze.json 是唯一配置来源：解析 → 验证 freeze_id → 生成
    Holdout runtime config。任何不一致 fail-fast（在 sealed 访问 / API / 输出前）。
    """
    freeze = json.loads(Path(freeze_json_path).read_text("utf-8"))
    _validate_freeze_json(freeze)
    return Gate3HoldoutConfig(
        gate3_system_freeze_id=EXPECTED_FREEZE_ID,
        gate3_dataset_freeze_id=EXPECTED_GATE3_DATASET_FREEZE_ID,
        holdout_evaluation_set_id=EXPECTED_HOLDOUT_EVALUATION_SET_ID,
        holdout_case_count=EXPECTED_HOLDOUT_CASE_COUNT,
        actual_execution_source_commit=actual_execution_source_commit,
        retrieval=dict(freeze["retrieval_runtime_config"]),
        planner=dict(freeze["planner"]),
        generator=dict(freeze["generator"]),
        judge=dict(freeze["judge"]),
        holdout_jsonl_path=holdout_jsonl_path,
        private_manifest_path=private_manifest_path,
        frozen_index_manifest_path=frozen_index_manifest_path,
        corpus_root=corpus_root,
        output_root=output_root,
    )


def validate_frozen_knobs(config: Gate3HoldoutConfig) -> None:
    """验证 frozen knobs 可构造到配置对象层（不实例化客户端/不建 index）。

    检查各 section 必填键存在且类型/hex 合法；不读 holdout 文件、不开 private
    manifest、不创建 OpenAI/DeepSeek client。
    """
    retrieval = config.retrieval
    for key in ("chunk_strategy", "chunk_budget_policy", "embedding_provider",
                "embedding_model", "merge_policy", "adaptive_policy"):
        _check_nonempty_no_ws(retrieval.get(key), f"retrieval.{key}")
    for key in ("chunk_size", "chunk_overlap", "dense_candidate_k",
                "sparse_candidate_k", "top_k", "max_evidence_items",
                "max_retrieval_calls"):
        if (type(retrieval.get(key)) is not int
                or isinstance(retrieval.get(key), bool)
                or retrieval.get(key) <= 0):
            raise ValueError(f"retrieval.{key} 必须是严格正整数")
    for key in ("rrf_k", "merge_rrf_k"):
        value = retrieval.get(key)
        if isinstance(value, bool) or type(value) not in (int, float) or value <= 0:
            raise ValueError(f"retrieval.{key} 必须是有界正数")
    if retrieval.get("rrf_tie_breaker") != "chunk_id_asc":
        raise ValueError("retrieval.rrf_tie_breaker 必须是 chunk_id_asc")
    planner = config.planner
    for key in ("provider", "model", "prompt_version"):
        _check_nonempty_no_ws(planner.get(key), f"planner.{key}")
    # planner prompt SHA 由 freeze_id canonical 重算整体绑定，不在 planner section 内。
    for key in ("max_tokens", "max_retries"):
        if (type(planner.get(key)) is not int or isinstance(planner.get(key), bool)
                or planner.get(key) < 0):
            raise ValueError(f"planner.{key} 必须是非负整数")
    generator = config.generator
    for key in ("provider", "model", "prompt_version"):
        _check_nonempty_no_ws(generator.get(key), f"generator.{key}")
    for key in ("max_tokens", "max_retries"):
        if (type(generator.get(key)) is not int
                or isinstance(generator.get(key), bool)
                or generator.get(key) < 0):
            raise ValueError(f"generator.{key} 必须是非负整数")
    judge = config.judge
    for key in ("provider", "model", "prompt_version"):
        _check_nonempty_no_ws(judge.get(key), f"judge.{key}")
    _check_hex(judge.get("prompt_sha256", ""), 64, "judge.prompt_sha256")
    for key in ("max_tokens", "max_retries"):
        if (type(judge.get(key)) is not int or isinstance(judge.get(key), bool)
                or judge.get(key) < 0):
            raise ValueError(f"judge.{key} 必须是非负整数")


def _git_head(repo: str) -> str:
    return subprocess.check_output(
        ["git", "-C", repo, "rev-parse", "HEAD"], text=True
    ).strip()


# ---------------------------------------------------------------------------
# 一次性 Attempt Ledger
# ---------------------------------------------------------------------------


def read_attempt_ledger(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"schema_version": HOLDOUT_ATTEMPT_LEDGER_SCHEMA, "attempts": []}
    ledger = json.loads(p.read_text("utf-8"))
    if ledger.get("schema_version") != HOLDOUT_ATTEMPT_LEDGER_SCHEMA:
        raise ValueError("attempt ledger schema_version 不一致")
    return ledger


def check_attempt_allowed(path: str) -> None:
    """正式运行前调用：任何 running/completed/failed_system → 禁止第二次开始；
    invalid_infrastructure → 不得自动重跑（需 Reviewer audit）。"""
    ledger = read_attempt_ledger(path)
    for attempt in ledger.get("attempts", []):
        status = attempt.get("status")
        if status in _ACTIVE_BLOCKING_STATUSES:
            raise RuntimeError(
                f"attempt {attempt.get('attempt_id')} 状态 {status}："
                "已有 active/terminal attempt，禁止第二次开始"
            )
        if status == _REVIEWER_GATED_STATUS:
            raise RuntimeError(
                "invalid_infrastructure attempt：不得自动重跑；"
                "需 Reviewer audit 后显式授权/拒绝替代 attempt"
            )


def atomic_create_attempt(path: str, config: Gate3HoldoutConfig) -> dict:
    """09B 首次访问 sealed 前原子登记 attempt；09A preflight 不得调用。

    一旦存在任何 running/completed/failed_system：拒绝第二次开始；
    invalid_infrastructure：拒绝自动重跑。
    """
    check_attempt_allowed(path)
    attempt = {
        "attempt_id": _sha256_bytes(_canonical({
            "gate3_system_freeze_id": config.gate3_system_freeze_id,
            "gate3_dataset_freeze_id": config.gate3_dataset_freeze_id,
            "holdout_evaluation_set_id": config.holdout_evaluation_set_id,
            "actual_execution_source_commit": config.actual_execution_source_commit,
        }))[:12],
        "gate3_system_freeze_id": config.gate3_system_freeze_id,
        "gate3_dataset_freeze_id": config.gate3_dataset_freeze_id,
        "holdout_evaluation_set_id": config.holdout_evaluation_set_id,
        "actual_execution_source_commit": config.actual_execution_source_commit,
        "started_at": None,
        "status": "prepared",
    }
    ledger = read_attempt_ledger(path)
    ledger.setdefault("attempts", []).append(attempt)
    write_text_atomic(Path(path), _canonical(ledger).decode("utf-8"))
    return attempt


def assert_no_forbidden_overrides(argv: list) -> None:
    """Runner 禁止提供性能 override；CLI 不应包含这些参数。"""
    for arg in argv:
        if arg.startswith("--") and arg.split("=")[0] in FORBIDDEN_OVERRIDE_ARGS:
            raise SystemExit(f"禁止性能 override: {arg}")


def _check_path_contract(path: str, label: str) -> None:
    """只检查 path string / contract；绝不 read_text/open。"""
    if type(path) is not str or not path.strip():
        raise ValueError(f"{label} 必须是合法路径字符串")


def preflight_holdout(
    *,
    repo: str,
    freeze_json_path: str,
    holdout_jsonl_path: str,
    private_manifest_path: str,
    frozen_index_manifest_path: str,
    corpus_root: str,
    output_root: str,
    attempt_ledger_path: str,
) -> dict:
    """09A dry-run/preflight：不读 holdout 内容、不开 private manifest、不创建
    LLM client、不建 index；0 LLM / 0 retrieval / 0 embedding。

    tracked-clean → actual HEAD → Freeze JSON SHA/ID → frozen config → 无 override →
    output 目标不存在 → attempt ledger 未消费 → frozen knobs 可构造。
    """
    check_git_tracked_clean(repo)
    head = _git_head(repo)
    for label, value in (
        ("freeze-json", freeze_json_path), ("holdout-jsonl", holdout_jsonl_path),
        ("private-manifest", private_manifest_path),
        ("frozen-index-manifest", frozen_index_manifest_path),
        ("corpus-root", corpus_root), ("output-root", output_root),
        ("attempt-ledger", attempt_ledger_path),
    ):
        _check_path_contract(value, label)

    config = build_holdout_config_from_freeze(
        freeze_json_path,
        actual_execution_source_commit=head,
        holdout_jsonl_path=holdout_jsonl_path,
        private_manifest_path=private_manifest_path,
        frozen_index_manifest_path=frozen_index_manifest_path,
        corpus_root=corpus_root,
        output_root=output_root,
    )
    validate_frozen_knobs(config)

    if Path(output_root).exists():
        raise FileExistsError(f"output-root 已存在，禁止覆盖: {output_root}")
    check_attempt_allowed(attempt_ledger_path)

    return {
        "preflight": "ok",
        "holdout_run_id": config.holdout_run_id,
        "gate3_system_freeze_id": config.gate3_system_freeze_id,
        "gate3_dataset_freeze_id": config.gate3_dataset_freeze_id,
        "holdout_evaluation_set_id": config.holdout_evaluation_set_id,
        "holdout_case_count": config.holdout_case_count,
        "actual_execution_source_commit": head,
        "frozen_code_baseline_commit": EXPECTED_FROZEN_BASELINE,
        "llm_calls": 0,
        "retrieval_calls": 0,
        "embedding_calls": 0,
        "sealed_read": False,
    }
