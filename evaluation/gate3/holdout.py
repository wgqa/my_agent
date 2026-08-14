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
import os
import subprocess
import types
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from core.generator.deepseek_gen import DeepSeekGenerator
from core.query_planning.openai_compatible import OpenAICompatibleQueryPlanner
from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.gate3.adaptive_dev import (
    EXPECTED_CORPUS_FILE_COUNT,
    EXPECTED_CORPUS_ID,
    _canonical_json,
    _check_hex,
    _check_nonempty_no_ws,
    _sha256_bytes,
    _sha256_file,
    build_shared_index,
    check_git_tracked_clean,
    load_corpus,
    write_text_atomic,
)
from evaluation.gate3.e2e import (
    GATE3_E2E_METRICS_SCHEMA_VERSION,
    GATE3_E2E_RESULT_SCHEMA_VERSION,
    AnswerJudge,
    E2EGroundedAnswerPort,
    GenerationCase,
    _count_statuses,
    assert_no_secrets,
    compute_answer_metrics,
    compute_deterministic_metrics,
    load_run_case_results,
    load_run_cited_evidence,
    run_generation_cases,
    should_call_judge,
)
from evaluation.gate3.evaluation_set import Gate3EvaluationSet

GATE3_HOLDOUT_SCHEMA_VERSION = "gate3_holdout_run_v1"
HOLDOUT_ATTEMPT_LEDGER_SCHEMA = "holdout_attempt_ledger_v1"

# Freeze-bound 期望常量（来自已审计 gate3_system_freeze.json）。
EXPECTED_FREEZE_ID = "2ec11a69b173"
EXPECTED_FROZEN_BASELINE = "fed9d15b950fe543d1afc99a2a21a5ad5d299320"
EXPECTED_GATE3_DATASET_FREEZE_ID = "257fa0d0a6d6"
EXPECTED_HOLDOUT_EVALUATION_SET_ID = "79a6bc0814a3"
EXPECTED_HOLDOUT_CASE_COUNT = 12
# 预先公开的冻结值（来源 docs/experiments/gate3_data_freeze.json，已核对一致）。
# expected 必须来自公开冻结材料 / Reviewer-frozen constants，禁止从 sealed 推导。
EXPECTED_HOLDOUT_JSONL_SHA256 = (
    "00bfcac2fe553f3edeefcc281db5c2aecaa380e9f41fd3ecfb98ec7a4796fe61"
)
EXPECTED_PRIVATE_MANIFEST_SHA256 = (
    "b34bb2d16d29dcd22c5d096dda370b044ffc64c81c9c590df7086926db2205c0"
)

# attempt 状态：prepared / running / completed / invalid_infrastructure / failed_system。
# 最保守规则：ledger 存在任何合法 attempt（含 prepared）即禁止自动创建另一个；
# invalid_infrastructure 的替代由 Reviewer 单独放行，不留自动后门。
HOLDOUT_ATTEMPT_STATUSES = (
    "prepared", "running", "completed",
    "invalid_infrastructure", "failed_system",
)

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
    # 执行时验证 sealed 后才填入的 Holdout JSONL SHA；空时身份为 preflight（09A）。
    holdout_jsonl_sha256: str = ""
    # 全部继承自 gate3_system_freeze.json（唯一配置来源）
    retrieval: dict = field(default_factory=dict)
    planner: dict = field(default_factory=dict)
    generator: dict = field(default_factory=dict)
    judge: dict = field(default_factory=dict)
    # 预先公开的冻结值（来源 docs/experiments/gate3_data_freeze.json /
    # Reviewer-frozen constants）；执行前必须验证，不进 run 身份。
    expected_corpus_id: str = ""
    expected_corpus_file_count: int = 0
    expected_holdout_jsonl_sha256: str = ""
    expected_private_manifest_sha256: str = ""
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
        if self.holdout_jsonl_sha256:
            _check_hex(self.holdout_jsonl_sha256, 64, "holdout_jsonl_sha256")
        if self.expected_corpus_id:
            _check_hex(self.expected_corpus_id, 12, "expected_corpus_id")
        if (type(self.expected_corpus_file_count) is not int
                or isinstance(self.expected_corpus_file_count, bool)
                or self.expected_corpus_file_count < 0):
            raise ValueError("expected_corpus_file_count 必须是整数（非负）")
        for name in ("expected_holdout_jsonl_sha256",
                     "expected_private_manifest_sha256"):
            if getattr(self, name):
                _check_hex(getattr(self, name), 64, name)
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
        # preflight / registration 身份（不含 Holdout JSONL SHA）。
        return _sha256_bytes(_canonical(self.identity_payload()))[:12]

    def formal_identity_payload(self) -> dict:
        """正式 Holdout 身份：在验证 sealed manifest 后，把 holdout_jsonl_sha256
        纳入身份。此时 holdout_run_id（a1dc0a4bab03）只属历史 09A preflight，
        不是最终 Holdout run ID。"""
        if not self.holdout_jsonl_sha256:
            raise ValueError(
                "holdout_jsonl_sha256 未验证，无法生成 formal identity"
            )
        payload = dict(self.identity_payload())
        payload["holdout_jsonl_sha256"] = self.holdout_jsonl_sha256
        return payload

    @property
    def formal_holdout_run_id(self) -> str:
        return _sha256_bytes(_canonical(self.formal_identity_payload()))[:12]

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
        expected_corpus_id=EXPECTED_CORPUS_ID,
        expected_corpus_file_count=EXPECTED_CORPUS_FILE_COUNT,
        expected_holdout_jsonl_sha256=EXPECTED_HOLDOUT_JSONL_SHA256,
        expected_private_manifest_sha256=EXPECTED_PRIVATE_MANIFEST_SHA256,
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
    """严格读取并校验 ledger：schema、attempts 类型、每条 attempt 结构、合法 status。

    任何损坏/未知/缺失一律 fail-closed（ValueError）。
    """
    p = Path(path)
    if not p.exists():
        return {"schema_version": HOLDOUT_ATTEMPT_LEDGER_SCHEMA, "attempts": []}
    try:
        ledger = json.loads(p.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"attempt ledger 损坏：{exc}") from exc
    if not isinstance(ledger, dict):
        raise ValueError("attempt ledger 必须是 JSON object")
    if ledger.get("schema_version") != HOLDOUT_ATTEMPT_LEDGER_SCHEMA:
        raise ValueError("attempt ledger schema_version 不一致或缺失")
    attempts = ledger.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("attempt ledger attempts 必须是数组")
    required = ("attempt_id", "gate3_system_freeze_id", "gate3_dataset_freeze_id",
                "holdout_evaluation_set_id", "actual_execution_source_commit",
                "started_at", "status")
    for i, a in enumerate(attempts):
        if not isinstance(a, dict):
            raise ValueError(f"attempt[{i}] 必须是 object")
        missing = [f for f in required if f not in a]
        if missing:
            raise ValueError(f"attempt[{i}] 缺少字段: {missing}")
        if a["status"] not in HOLDOUT_ATTEMPT_STATUSES:
            raise ValueError(
                f"attempt[{i}] 非法 status {a['status']!r}（fail-closed）"
            )
    return ledger


def _check_attempt_allowed_ledger(ledger: dict) -> None:
    """最保守：ledger 存在任何合法 attempt（含 prepared）即禁止自动创建另一个。

    invalid_infrastructure 的替代由 Reviewer 单独放行，本层不留自动后门。
    """
    for attempt in ledger.get("attempts", []):
        raise RuntimeError(
            f"attempt {attempt.get('attempt_id')} 状态 {attempt.get('status')}："
            "ledger 已存在合法 attempt，禁止自动创建另一个；"
            "invalid_infrastructure 替代需 Reviewer 单独放行"
        )


def check_attempt_allowed(path: str) -> None:
    """正式运行前调用：ledger 存在任何合法 attempt 即拒绝（含 prepared）。"""
    _check_attempt_allowed_ledger(read_attempt_ledger(path))


def atomic_create_attempt(path: str, config: Gate3HoldoutConfig) -> dict:
    """09B 首次访问 sealed 前原子登记 attempt；09A preflight 不得调用。

    跨进程互斥：sibling lock 文件 O_CREAT|O_EXCL|O_WRONLY；持锁期间完成
    read → validate → check → append → write。异常残留 lock 不自动删除
    （fail-closed，交 Reviewer 判断）；正常完成才释放锁。
    """
    lock_path = str(Path(path)) + ".lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(
            f"ledger 锁已存在: {lock_path}（可能是异常残留，Reviewer 判断）"
        ) from None
    try:
        os.close(fd)
        ledger = read_attempt_ledger(path)  # 严格校验
        _check_attempt_allowed_ledger(ledger)  # 任何合法 attempt 均拒绝
        started_at = datetime.now(timezone.utc).isoformat()
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
            "started_at": started_at,
            "status": "prepared",
        }
        ledger.setdefault("attempts", []).append(attempt)
        write_text_atomic(Path(path), _canonical(ledger).decode("utf-8"))
    except BaseException:
        # fail-closed：保留 lock，不当作没发生，交 Reviewer 判断。
        raise
    else:
        os.unlink(lock_path)  # 正常完成释放锁
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


# ---------------------------------------------------------------------------
# 09B：正式执行器（09C 写死顺序；注入 provider 供 synthetic 测试）
# ---------------------------------------------------------------------------


class HoldoutInfrastructureFailure(RuntimeError):
    """只有真正无法形成有效实验的基础设施故障才抛出；持久化为 invalid_infrastructure。"""


def _find_attempt(ledger: dict, attempt_id: str) -> tuple[int, dict]:
    for i, a in enumerate(ledger.get("attempts", [])):
        if a.get("attempt_id") == attempt_id:
            return i, a
    raise KeyError(f"attempt {attempt_id} 不存在")


_VALID_TRANSITIONS = {
    "prepared": ("running", "invalid_infrastructure", "failed_system"),
    "running": ("completed", "invalid_infrastructure", "failed_system"),
    "completed": (),
    "invalid_infrastructure": (),
    "failed_system": (),
}


def update_attempt_status(path: str, attempt_id: str, new_status: str,
                          reason=None) -> None:
    """跨进程互斥地更新 attempt 状态（prepared→running→completed 等）。

    非法/终端状态后继续迁移一律拒绝。系统行为性失败（如 generator 空输出）不
    属于此处：那类 case 仍以 completed 收尾，把失败 case 记入正式结果。
    """
    if new_status not in HOLDOUT_ATTEMPT_STATUSES:
        raise ValueError(f"非法 status {new_status!r}")
    lock_path = str(Path(path)) + ".lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(f"ledger 锁已存在: {lock_path}") from None
    try:
        os.close(fd)
        ledger = read_attempt_ledger(path)
        idx, attempt = _find_attempt(ledger, attempt_id)
        if new_status not in _VALID_TRANSITIONS.get(attempt["status"], ()):
            raise ValueError(
                f"attempt {attempt_id} 非法迁移 {attempt['status']} -> {new_status}"
            )
        ledger["attempts"][idx]["status"] = new_status
        if reason is not None:
            ledger["attempts"][idx]["reason"] = reason
        write_text_atomic(Path(path), _canonical(ledger).decode("utf-8"))
    except BaseException:
        raise
    else:
        os.unlink(lock_path)


def bind_attempt_formal_identity(
    path: str,
    attempt_id: str,
    *,
    formal_holdout_run_id: str,
    holdout_jsonl_sha256: str,
) -> None:
    """sealed 校验成功后、进入 running 前，把 formal identity 原子绑定进 attempt。

    只在 prepared 状态可绑定；一旦绑定不允许再修改；重复绑定直接拒绝（fail-closed）。
    状态序列：prepared → bind formal identity → running → completed。
    """
    _check_hex(formal_holdout_run_id, 12, "formal_holdout_run_id")
    _check_hex(holdout_jsonl_sha256, 64, "holdout_jsonl_sha256")
    lock_path = str(Path(path)) + ".lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(f"ledger 锁已存在: {lock_path}") from None
    try:
        os.close(fd)
        ledger = read_attempt_ledger(path)
        idx, attempt = _find_attempt(ledger, attempt_id)
        if attempt["status"] != "prepared":
            raise ValueError(
                f"formal identity 只能在 prepared 状态绑定，当前 "
                f"{attempt['status']!r}"
            )
        if attempt.get("formal_holdout_run_id") or attempt.get(
            "holdout_jsonl_sha256"
        ):
            raise RuntimeError(
                f"attempt {attempt_id} formal identity 已绑定，禁止重绑"
            )
        ledger["attempts"][idx]["formal_holdout_run_id"] = formal_holdout_run_id
        ledger["attempts"][idx]["holdout_jsonl_sha256"] = holdout_jsonl_sha256
        write_text_atomic(Path(path), _canonical(ledger).decode("utf-8"))
    except BaseException:
        raise
    else:
        os.unlink(lock_path)


def validate_sealed(manifest: dict, holdout_text: str,
                    config: Gate3HoldoutConfig) -> dict:
    """验证 sealed private manifest + Holdout JSONL（仅 09C 授权后调用）。

    private manifest 文件身份由公开冻结 raw SHA 锁定（read_real_sealed_inputs
    校验），本函数只做结构字段校验：dataset freeze id、holdout evaluation_set_id、
    case_count、manifest recorded Holdout SHA、duplicate case_id、Holdout case 数。
    返回 verified 信息（含 holdout_jsonl_sha256）。
    """
    if not isinstance(manifest, dict):
        raise HoldoutInfrastructureFailure("private manifest 不是 JSON object")
    if manifest.get("gate3_dataset_freeze_id") != config.gate3_dataset_freeze_id:
        raise HoldoutInfrastructureFailure(
            "private manifest gate3_dataset_freeze_id 与配置不一致"
        )
    if manifest.get("holdout_evaluation_set_id") != config.holdout_evaluation_set_id:
        raise HoldoutInfrastructureFailure(
            "private manifest holdout_evaluation_set_id 与配置不一致"
        )
    if manifest.get("holdout_case_count") != config.holdout_case_count:
        raise HoldoutInfrastructureFailure(
            "private manifest holdout_case_count 与配置不一致"
        )
    holdout_sha = _sha256_bytes(holdout_text.encode("utf-8"))
    recorded_sha = manifest.get("holdout_jsonl_sha256")
    if not recorded_sha or recorded_sha != holdout_sha:
        raise HoldoutInfrastructureFailure(
            "Holdout JSONL SHA 与 private manifest 不一致"
        )
    case_ids: list[str] = []
    for line in holdout_text.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        cid = rec.get("case_id")
        if cid in case_ids:
            raise HoldoutInfrastructureFailure(f"Holdout JSONL 重复 case_id: {cid}")
        case_ids.append(cid)
    if len(case_ids) != config.holdout_case_count:
        raise HoldoutInfrastructureFailure(
            f"Holdout case 数 {len(case_ids)} 与配置 {config.holdout_case_count} 不一致"
        )
    return {"holdout_jsonl_sha256": holdout_sha, "case_count": len(case_ids)}


def _parse_generation_cases_from_holdout(holdout_text: str) -> list[GenerationCase]:
    """Generation 只加载 case_id + query（Gold 隔离，复用 GenerationCase）。"""
    cases: list[GenerationCase] = []
    seen: set[str] = set()
    for line in holdout_text.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        cid, query = rec.get("case_id"), rec.get("query")
        if type(cid) is not str or type(query) is not str:
            raise HoldoutInfrastructureFailure("Holdout case 缺少 case_id/query")
        if cid in seen:
            raise HoldoutInfrastructureFailure(f"Holdout JSONL 重复 case_id: {cid}")
        seen.add(cid)
        cases.append(GenerationCase(case_id=cid, query=query))
    return cases


def _verify_public_data_freeze(repo: str) -> None:
    """公开 dataset freeze（docs/experiments/gate3_data_freeze.json）交叉验证。

    文件存在则校验冻结值与 Reviewer-frozen constants 一致；缺失（如临时测试仓库）
    则跳过。确保最终 executor 绑定的是已公开冻结材料，而不是从 sealed 推导。
    """
    p = Path(repo) / "docs" / "experiments" / "gate3_data_freeze.json"
    if not p.is_file():
        return
    d = json.loads(p.read_text("utf-8"))
    for key, expected in (
        ("gate3_dataset_freeze_id", EXPECTED_GATE3_DATASET_FREEZE_ID),
        ("corpus_id", EXPECTED_CORPUS_ID),
        ("corpus_file_count", EXPECTED_CORPUS_FILE_COUNT),
        ("private_manifest_sha256", EXPECTED_PRIVATE_MANIFEST_SHA256),
    ):
        if d.get(key) != expected:
            raise RuntimeError(
                f"公开 data freeze {key} 不一致: {d.get(key)!r} != {expected!r}"
            )
    holdout = d.get("holdout")
    if not isinstance(holdout, dict):
        raise RuntimeError("公开 data freeze holdout 段缺失")
    if (holdout.get("evaluation_set_id") != EXPECTED_HOLDOUT_EVALUATION_SET_ID
            or holdout.get("case_count") != EXPECTED_HOLDOUT_CASE_COUNT
            or holdout.get("jsonl_sha256") != EXPECTED_HOLDOUT_JSONL_SHA256):
        raise RuntimeError("公开 data freeze holdout 段与冻结常量不一致")


def _validate_frozen_corpus_identity(config: Gate3HoldoutConfig) -> None:
    """attempt 创建前验证 frozen corpus identity（只算 corpus_id，不建索引）。

    读取 frozen index manifest → relative_paths → ExperimentCorpus.build(...) →
    actual corpus_id / file count；必须匹配公开冻结值，否则 reject（attempt 不创建、
    sealed 未读取、LLM 0 次）。不构建 embedding/index。
    """
    frozen = json.loads(Path(config.frozen_index_manifest_path).read_text("utf-8"))
    relative_paths = [
        entry["relative_path"] for entry in frozen.get("corpus_entries", [])
    ]
    if len(relative_paths) != config.expected_corpus_file_count:
        raise RuntimeError(
            f"frozen index manifest 文件数 {len(relative_paths)} != 公开冻结 "
            f"{config.expected_corpus_file_count}"
        )
    corpus = ExperimentCorpus.build(config.corpus_root, relative_paths)
    if corpus.corpus_id != config.expected_corpus_id:
        raise RuntimeError(
            f"corpus_id {corpus.corpus_id} != 公开冻结 "
            f"{config.expected_corpus_id}（frozen corpus 被改动？）"
        )
    if len(corpus.entries) != config.expected_corpus_file_count:
        raise RuntimeError(
            f"corpus 实际文件数 {len(corpus.entries)} != 公开冻结 "
            f"{config.expected_corpus_file_count}"
        )


def execute_holdout(
    config: Gate3HoldoutConfig,
    *,
    repo: str,
    freeze_json_path: str,
    output_root: str,
    attempt_ledger_path: str,
    sealed_read_fn=None,
    run_generation_fn=None,
    run_evaluation_fn=None,
) -> dict:
    """09C 正式执行顺序（写死）。steps 1-6 之前绝不开 sealed；formal identity
    只在验证 sealed manifest 后产生。

    sealed_read_fn / run_generation_fn / run_evaluation_fn 用于 synthetic 测试注入；
    真实调用链（read_real_sealed_inputs / run_holdout_generation /
    run_holdout_evaluation）由 CLI 在 09C 授权后注入。系统行为性失败（如 generator
    空输出）不终止——仍 completed，失败 case 记入正式结果；只有真正无法形成有效
    实验的基础设施故障才抛 HoldoutInfrastructureFailure 并持久化为
    invalid_infrastructure（不自动重跑）；未知异常一律 fail-closed 原样上抛，保留
    attempt，不自动重跑，交 Reviewer 判断。
    """
    # 1 tracked-clean
    check_git_tracked_clean(repo)
    # 2 actual git HEAD
    head = _git_head(repo)
    # 3 attempt 创建前 re-validate freeze_json_path 并要求
    #   actual_execution_source_commit == actual git HEAD；不一致 fail-fast，
    #   不创建 attempt。
    validate_frozen_knobs(config)
    freeze = json.loads(Path(freeze_json_path).read_text("utf-8"))
    _validate_freeze_json(freeze)
    for section, label in (("retrieval_runtime_config", "retrieval"),
                           ("planner", "planner"),
                           ("generator", "generator"),
                           ("judge", "judge")):
        if getattr(config, label) != freeze[section]:
            raise RuntimeError(
                f"config.{label} 与 freeze {label} 不一致；拒绝创建 attempt"
            )
    if config.actual_execution_source_commit != head:
        raise RuntimeError(
            f"config.actual_execution_source_commit "
            f"{config.actual_execution_source_commit} != actual git HEAD {head}；"
            "拒绝创建 attempt"
        )
    # 缺少 provider 时在创建 attempt 前即 fail-closed（防止绕过真实 sealed 访问）
    if sealed_read_fn is None or run_generation_fn is None:
        raise HoldoutInfrastructureFailure(
            "未注入 sealed_read_fn / run_generation_fn；真实 sealed/生成链待 09C 授权"
        )
    # 3b 公开 dataset freeze 交叉验证（文件存在则校验常量一致）
    _verify_public_data_freeze(repo)
    # 3c 真实路径：API Key 前置检查（缺失 → NO attempt / NO sealed / 禁止输出 key）
    if run_generation_fn is run_holdout_generation and not os.getenv(
        "DEEPSEEK_API_KEY"
    ):
        raise RuntimeError(
            "缺少 DEEPSEEK_API_KEY 环境变量：不创建 attempt、不读取 sealed"
        )
    # 3d 真实路径：attempt 前验证 frozen corpus identity
    if run_generation_fn is run_holdout_generation:
        _validate_frozen_corpus_identity(config)
    # 4 check output not exist
    out = Path(output_root)
    if out.exists():
        raise FileExistsError(f"output-root 已存在: {output_root}")
    # 5 check ledger/lock
    check_attempt_allowed(attempt_ledger_path)
    # 6 atomic_create_attempt(prepared)
    attempt = atomic_create_attempt(attempt_ledger_path, config)
    attempt_id = attempt["attempt_id"]
    try:
        # ========== 此后才第一次允许访问 sealed ==========
        # 7 read + validate private manifest；8 hash Holdout JSONL
        # 9 verify evaluation_set_id / case_count / SHA
        manifest, holdout_text = sealed_read_fn()
        verified = validate_sealed(manifest, holdout_text, config)
        # 10 把 Holdout JSON SHA 纳入最终正式 run identity
        formal_config = replace(
            config, holdout_jsonl_sha256=verified["holdout_jsonl_sha256"]
        )
        formal_id = formal_config.formal_holdout_run_id
        # 10b formal identity 原子绑定进 ledger（prepared→bind→running；不可再改）
        bind_attempt_formal_identity(
            attempt_ledger_path, attempt_id,
            formal_holdout_run_id=formal_id,
            holdout_jsonl_sha256=verified["holdout_jsonl_sha256"],
        )
        # 11 status → running
        update_attempt_status(attempt_ledger_path, attempt_id, "running")
        # 12 Generation 仅加载 case_id + query
        generation_cases = _parse_generation_cases_from_holdout(holdout_text)
        # 13 Planner → Runtime → Retrieval → Generator；14 generation artifact 持久化
        gen_output = run_generation_fn(generation_cases, formal_config, str(out))
        # 15 再读取 Gold 做 deterministic evaluation + Judge
        eval_output = {}
        if run_evaluation_fn is not None:
            eval_output = run_evaluation_fn(gen_output, formal_config, str(out))
        # 16 写最终 artifacts（由 run_generation_fn / run_evaluation_fn 内完成写入）
        # 17 status → completed
        update_attempt_status(attempt_ledger_path, attempt_id, "completed")
        return {
            "formal_holdout_run_id": formal_id,
            "preflight_holdout_run_id": config.holdout_run_id,
            "holdout_jsonl_sha256": verified["holdout_jsonl_sha256"],
            "actual_execution_source_commit": head,
            "generation_cases": len(generation_cases),
            "generation_output": gen_output,
            "evaluation_output": eval_output,
            "status": "completed",
        }
    except HoldoutInfrastructureFailure as exc:
        update_attempt_status(
            attempt_ledger_path, attempt_id, "invalid_infrastructure",
            reason=str(exc),
        )
        raise


# ---------------------------------------------------------------------------
# 09B-R1：真实 sealed reader + 真实 Holdout Generation/Evaluation wiring
# （本阶段只实现并注入；HOLDOUT_EXECUTION_AUTHORIZED 未设置时不会执行）
# ---------------------------------------------------------------------------


def _formal_config_dict(config: Gate3HoldoutConfig) -> dict:
    """formal config 的落盘字典：identity + holdout_run_id + formal_holdout_run_id
    + holdout_jsonl_sha256（sealed 校验通过后即不可变）。"""
    payload = dict(config.identity_payload())
    payload["schema_version"] = config.schema_version
    payload["evaluation_schema_version"] = config.evaluation_schema_version
    payload["holdout_run_id"] = config.holdout_run_id
    payload["formal_holdout_run_id"] = config.formal_holdout_run_id
    payload["holdout_jsonl_sha256"] = config.holdout_jsonl_sha256
    return payload


def read_real_sealed_inputs(config: Gate3HoldoutConfig) -> tuple[dict, str]:
    """09C 真实 sealed reader：只从 config 读取 private manifest + Holdout JSONL。

    路径只来自 config（private_manifest_path / holdout_jsonl_path）；不得 list
    sealed 目录、不得猜文件名。读取 raw bytes 后先校验公开冻结的 raw SHA
    （expected 来自公开 dataset freeze / Reviewer-frozen constants，禁止从 sealed
    推导 expected），再解析返回。09B-R1 只实现与单测，不调用；09C 授权后才允许。
    """
    manifest_path = Path(config.private_manifest_path)
    jsonl_path = Path(config.holdout_jsonl_path)
    if not manifest_path.is_file():
        raise HoldoutInfrastructureFailure(
            f"private manifest 不存在: {manifest_path}")
    if not jsonl_path.is_file():
        raise HoldoutInfrastructureFailure(f"Holdout JSONL 不存在: {jsonl_path}")
    try:
        manifest_raw = manifest_path.read_bytes()
    except OSError as exc:
        raise HoldoutInfrastructureFailure(
            f"private manifest 读取失败: {exc}") from exc
    try:
        holdout_raw = jsonl_path.read_bytes()
    except OSError as exc:
        raise HoldoutInfrastructureFailure(
            f"Holdout JSONL 读取失败: {exc}") from exc
    if config.expected_private_manifest_sha256:
        actual = _sha256_bytes(manifest_raw)
        if actual != config.expected_private_manifest_sha256:
            raise HoldoutInfrastructureFailure(
                f"private manifest raw SHA {actual} != 公开冻结 "
                f"{config.expected_private_manifest_sha256}"
            )
    if config.expected_holdout_jsonl_sha256:
        actual = _sha256_bytes(holdout_raw)
        if actual != config.expected_holdout_jsonl_sha256:
            raise HoldoutInfrastructureFailure(
                f"Holdout raw SHA {actual} != 公开冻结 "
                f"{config.expected_holdout_jsonl_sha256}"
            )
    try:
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HoldoutInfrastructureFailure(
            f"private manifest 解析失败: {exc}") from exc
    try:
        holdout_text = holdout_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HoldoutInfrastructureFailure(
            f"Holdout JSONL 解码失败: {exc}") from exc
    return manifest, holdout_text


def run_holdout_generation(
    generation_cases,
    config: Gate3HoldoutConfig,
    run_dir: str,
) -> dict:
    """真实 Holdout Generation 链：Frozen Corpus → 冻结索引 → Real Planner →
    Adaptive Runtime → Retrieval → RRF merge v2 → Verifier → Real Generator →
    Citation。签名只接收 generation_cases(case_id+query) / formal config /
    run_dir，绝不接收 Holdout Gold。Generation Artifact 先落盘后才返回。

    复用现有生产能力（build_shared_index / run_generation_cases /
    OpenAICompatibleQueryPlanner / DeepSeekGenerator / E2EGroundedAnswerPort），
    不复制任何新 RAG 算法。
    """
    if not generation_cases:
        raise HoldoutInfrastructureFailure("Holdout generation cases 为空")
    if not config.holdout_jsonl_sha256:
        raise RuntimeError("formal config 未绑定 holdout_jsonl_sha256")

    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量")

    corpus_path = Path(config.corpus_root)
    frozen_manifest = json.loads(
        Path(config.frozen_index_manifest_path).read_text("utf-8"))
    relative_paths = [
        entry["relative_path"] for entry in frozen_manifest.get("corpus_entries", [])
    ]
    if not relative_paths:
        raise HoldoutInfrastructureFailure("冻结索引 corpus_entries 为空")
    corpus = ExperimentCorpus.build(str(corpus_path), relative_paths)
    basename_map = load_corpus(str(corpus_path), relative_paths)

    run = Path(run_dir)
    if run.exists():
        raise FileExistsError(f"输出目录已存在，禁止覆盖: {run}")
    run.mkdir(parents=True)

    workspace = run.parent / "workspaces" / config.formal_holdout_run_id
    index = build_shared_index(
        str(corpus_path), relative_paths, str(workspace / "vector_store"))
    index_manifest = dict(index.build_manifest)
    index_manifest["index_sha256"] = _sha256_bytes(_canonical_json(index_manifest))

    retrieval = config.retrieval
    planner = OpenAICompatibleQueryPlanner(
        provider=config.planner["provider"],
        model=config.planner["model"],
        api_key=api_key,
        base_url="https://api.deepseek.com/v1",
    )
    generator = DeepSeekGenerator(
        api_key=api_key,
        model=config.generator["model"],
        temperature=config.generator["temperature"],
        timeout_seconds=config.generator["timeout"],
        max_retries=config.generator["max_retries"],
        max_total_tokens=4096,
        max_output_tokens=config.generator["max_tokens"],
    )
    answer_port = E2EGroundedAnswerPort(
        generator,
        direct_model=config.planner["model"],
        direct_api_key=api_key,
        direct_base_url="https://api.deepseek.com/v1",
    )
    records, cited_evidence_records = run_generation_cases(
        generation_cases,
        index=index, basename_map=basename_map,
        planner=planner, generator=generator, answer_port=answer_port,
        top_k=retrieval["top_k"],
        max_retrieval_calls=retrieval["max_retrieval_calls"],
        max_evidence_items=retrieval["max_evidence_items"],
        merge_policy=retrieval["merge_policy"],
        merge_rrf_k=retrieval["merge_rrf_k"],
    )
    write_text_atomic(
        run / "run_config.json",
        _canonical_json(_formal_config_dict(config)).decode("utf-8"),
    )
    write_text_atomic(
        run / "index_manifest.json",
        _canonical_json(index_manifest).decode("utf-8"),
    )
    case_lines = "\n".join(
        _canonical_json(r).decode("utf-8") for r in records
    )
    write_text_atomic(run / "case_results.jsonl", case_lines + "\n")
    cited_lines = "\n".join(
        _canonical_json(r).decode("utf-8") for r in cited_evidence_records
    )
    write_text_atomic(run / "cited_evidence.jsonl", cited_lines + "\n")
    for f in ("run_config.json", "index_manifest.json", "case_results.jsonl",
              "cited_evidence.jsonl"):
        assert_no_secrets((run / f).read_text("utf-8"))
    return {
        "formal_holdout_run_id": config.formal_holdout_run_id,
        "case_count": len(records),
        "status_counts": _count_statuses(records),
    }


def build_holdout_comparison_report(
    config: Gate3HoldoutConfig, metrics: dict
) -> str:
    """Holdout 一次性的 Markdown 评测报告（presentation，非指标定义）。"""
    d = metrics["deterministic"]
    a = metrics["answer"]
    lines = ["# G3-HOLDOUT-09C 一次性 Holdout 答案评测报告", ""]
    lines.append(f"- formal_holdout_run_id = {config.formal_holdout_run_id}")
    lines.append(
        f"- holdout_evaluation_set_id = {config.holdout_evaluation_set_id}"
    )
    lines.append(f"- case_count = {metrics['case_count']}")
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
        f"{a['citation_valid_denominator']} = {a['citation_valid_case_rate']:.4f} |"
    )
    lines.append(f"| unsupported claim case | {a['unsupported_claim_case_count']} |")
    lines.append(f"| answer pass case | {a['answer_pass_case_count']} |")
    lines.append(f"| invalid judge | {a['invalid_judge_case_count']} |")
    lines.append(f"| no-answer | {a['no_answer_case_count']} |")
    lines.append(f"| zero-obligation | {a['zero_obligation_case_count']} |")
    lines.append("")
    lines.append("## 检索（确定性）层")
    lines.append("")
    lines.append(
        f"- obligation 覆盖（retrieval）：{d['obligation']['obligation_covered']}"
        f"/{d['obligation']['obligation_total']} = "
        f"{d['obligation']['obligation_coverage_rate']:.4f}"
    )
    lines.append("")
    lines.append("> 一次性 Holdout 封卷评测；evaluation schema "
                 "gate3_e2e_metrics_v1 不改数学定义。")
    return "\n".join(lines)


def run_holdout_evaluation(
    gen_output,
    config: Gate3HoldoutConfig,
    run_dir: str,
    *,
    judge_client=None,
) -> dict:
    """Holdout-specific evaluation：生成已落盘后离线读取 + LLM Judge。

    不直接调用 run_e2e_evaluation()（其绑定 Dev identity / dev_jsonl_path）；
    复用公共计算能力：AnswerJudge / should_call_judge / evaluate_citations /
    compute_deterministic_metrics / compute_answer_metrics。evaluation schema 仍
    gate3_e2e_metrics_v1，不改数学定义。Gold 只在 evaluation 阶段读取（生成已
    落盘，阶段边界成立）。
    """
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量")

    run = Path(run_dir)
    records = load_run_case_results(run)
    cited_map = load_run_cited_evidence(run)
    if len(records) != config.holdout_case_count:
        raise HoldoutInfrastructureFailure(
            f"case_results 数量 {len(records)} 与 holdout 配置 "
            f"{config.holdout_case_count} 不一致"
        )

    frozen = json.loads(
        Path(config.frozen_index_manifest_path).read_text("utf-8"))
    relative_paths = [
        entry["relative_path"] for entry in frozen.get("corpus_entries", [])
    ]
    corpus = ExperimentCorpus.build(config.corpus_root, relative_paths)
    # SHA guard：Generation 与 Evaluation 之间 Holdout 不得被改动（fail-closed）
    current_holdout_sha = _sha256_file(Path(config.holdout_jsonl_path))
    if current_holdout_sha != config.holdout_jsonl_sha256:
        raise HoldoutInfrastructureFailure(
            f"当前 Holdout 文件 SHA {current_holdout_sha} != 已绑定 formal SHA "
            f"{config.holdout_jsonl_sha256}（Generation 后被改动？）"
        )
    # Gold 只在 evaluation 阶段读取（生成已落盘）
    holdout_set = Gate3EvaluationSet.load_jsonl(
        config.holdout_jsonl_path, corpus)
    case_by_id = {c.case_id: c for c in holdout_set.cases}
    gen_ids = {r["case_id"] for r in records}
    holdout_ids = {c.case_id for c in holdout_set.cases}
    if gen_ids != holdout_ids:
        raise HoldoutInfrastructureFailure(
            f"evaluation case ID 集合与 generation 不一致："
            f"gen 独有 {sorted(gen_ids - holdout_ids)}、"
            f"holdout 独有 {sorted(holdout_ids - gen_ids)}"
        )

    judge_view = types.SimpleNamespace(
        judge_timeout=float(config.judge["timeout"]),
        judge_max_retries=int(config.judge["max_retries"]),
        judge_model=config.judge["model"],
        judge_temperature=float(config.judge["temperature"]),
        judge_max_tokens=int(config.judge["max_tokens"]),
    )
    judge = AnswerJudge(config=judge_view, api_key=api_key, client=judge_client)

    judgments = []
    for rec in records:
        case = case_by_id[rec["case_id"]]
        gold_obligations = [
            {"obligation_id": o.obligation_id, "description": o.description}
            for o in case.evidence_obligations
        ]
        cited = cited_map.get(rec["case_id"], [])
        if not case.evidence_obligations:
            # 零 obligation（unanswerable/no_retrieval/direct）不调 Judge：
            # 不允许凭空造 obligation，单独上报为 not_required / zero_obligation。
            judge_result = {"judge_status": "not_required",
                            "reason": "zero_obligation"}
        elif should_call_judge(rec, True):
            judge_result = judge.judge(
                rec["query"], rec["answer"], cited, gold_obligations)
        else:
            judge_result = {"judge_status": "not_generated"}
        judgments.append({
            "case_id": rec["case_id"],
            "judge_input": {
                "query": rec["query"],
                "answer": rec.get("answer"),
                "cited_evidence": cited,
                "gold_obligations": gold_obligations,
            },
            "judge_output": judge_result,
        })

    det = compute_deterministic_metrics(records, holdout_set, case_by_id)
    ans = compute_answer_metrics(records, judgments, holdout_set, case_by_id)
    metrics = {
        "schema_version": GATE3_E2E_METRICS_SCHEMA_VERSION,
        "deterministic": det,
        "answer": ans,
        "answerable_case_count": ans["answerable_case_count"],
        "case_count": len(records),
    }
    comparison = build_holdout_comparison_report(config, metrics)
    write_text_atomic(
        run / "answer_judgments.jsonl",
        "\n".join(_canonical_json(j).decode("utf-8") for j in judgments) + "\n",
    )
    write_text_atomic(
        run / "metrics.json", _canonical_json(metrics).decode("utf-8"))
    write_text_atomic(run / "comparison_report.md", comparison)
    write_text_atomic(
        run / "result.json",
        _canonical_json({
            "schema_version": GATE3_E2E_RESULT_SCHEMA_VERSION,
            "formal_holdout_run_id": config.formal_holdout_run_id,
            "holdout_run_id": config.holdout_run_id,
            "config": _formal_config_dict(config),
            "metrics": metrics,
        }).decode("utf-8"),
    )
    for f in ("answer_judgments.jsonl", "metrics.json", "comparison_report.md",
              "result.json"):
        assert_no_secrets((run / f).read_text("utf-8"))
    return metrics
