"""G5-ENV-02: minimal reproducibility contract tests.

Verifies, offline (no Retrieval/LLM/benchmark/model load):
- reproducibility/public_data_lock.json schema and pinned identity
  (repository / commit / path / corpus_id=870e5864df67 / file_count=37);
- every tracked experiment manifest's experiment_id binding to its directory;
- where the current ExperimentConfig schema matches (post-IMPL-20 aligned
  experiments) the tracked manifest config reconstructs the experiment_id;
  pre-IMPL-20 experiment_ids are recorded frozen references (schema evolution),
  so their binding is verified, not re-derived;
- no absolute local path / secret in tracked experiment configs or manifests.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import fields as dc_fields
from pathlib import Path

import pytest

from evaluation.experiment_config import ExperimentConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO_ROOT / "reproducibility" / "public_data_lock.json"

PINNED = {
    "repository": "wgqa/agent_data",
    "commit": "179f18e812ad63c36c5569de8e86c5ff9a931cb5",
    "path": "agent_ai_v1/02_corpus_candidate",
    "corpus_id": "870e5864df67",
    "file_count": 37,
}

# 绝对本地路径 / secret 扫描模式
_ABS_PATH_RE = re.compile(r"(?i)([a-z]:[\\/]|/users/|/home/)")
_SECRET_RE = re.compile(r"(?i)(sk-[a-z0-9]|authorization\s*:|bearer\s+[a-z0-9])")

_EXPERIMENT_FIELDS = {f.name for f in dc_fields(ExperimentConfig)}


def _lock() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _tracked_files(pattern: str):
    out = subprocess.run(
        ["git", "ls-files", pattern],
        capture_output=True, text=True, cwd=REPO_ROOT, check=True,
    )
    return [REPO_ROOT / p for p in out.stdout.splitlines() if p]


def _tracked_manifests():
    return _tracked_files("experiments/*/*/index_manifest.json")


def _exp_id(mf: Path) -> str:
    """experiment_id = 目录名（相对 REPO_ROOT 的二级路径）。"""
    return mf.relative_to(REPO_ROOT).parts[1]


def _reconstruct_id(cfg: dict) -> str:
    """当前 schema 的 experiment_id（IMPL-20 之后；含 budget/runtime 字段）。"""
    kwargs = {k: v for k, v in cfg.items() if k in _EXPERIMENT_FIELDS}
    if not {"embedding_provider", "embedding_model", "chunk_strategy",
            "chunk_size", "retriever_strategy"}.issubset(kwargs):
        return ""
    try:
        return ExperimentConfig(**kwargs).experiment_id
    except (TypeError, ValueError):
        return ""


# ---------------------------------------------------------------------- #
# public_data_lock
# ---------------------------------------------------------------------- #

def test_lock_schema_required_fields():
    lock = _lock()
    assert lock["schema_version"] == "gate5_public_data_lock_v1"
    for key in PINNED:
        assert key in lock, f"public_data_lock 缺少 {key}"


def test_lock_pinned_identity():
    lock = _lock()
    for key, expected in PINNED.items():
        assert lock[key] == expected, f"public_data_lock.{key} != {expected}"


# ---------------------------------------------------------------------- #
# tracked experiment identity
# ---------------------------------------------------------------------- #

def test_all_tracked_experiments_manifest_binding():
    """manifest.experiment_id == 目录名（冻结绑定），是历史身份的锚点。"""
    manifests = _tracked_manifests()
    assert manifests, "tracked index_manifest 为空"
    for mf in manifests:
        exp_id = _exp_id(mf)
        manifest = json.loads(mf.read_text(encoding="utf-8"))
        assert manifest["experiment_id"] == exp_id, (
            f"{mf} 内 experiment_id 与目录不一致"
        )


def test_current_schema_reconstruction_matches_aligned_experiments():
    """当前 schema 可重建身份的实验（IMPL-20 之后 aligned）必须匹配。"""
    matched = []
    for mf in _tracked_manifests():
        exp_id = _exp_id(mf)
        cfg = json.loads(mf.read_text(encoding="utf-8"))["config"]
        if _reconstruct_id(cfg) == exp_id:
            matched.append(exp_id)
    assert matched, "当前 schema 没有任何实验可重建身份"
    for eid in ("04fc6d2111a6", "b35b1102197e", "e680cdf278b2"):
        assert eid in matched, f"aligned 实验 {eid} 应能当前 schema 重建"


def test_pre_impl20_experiments_are_recorded_frozen_references():
    """pre-IMPL-20 实验 id 是记录的冻结引用（schema 演进），绑定必须成立。"""
    current_matched = set()
    for mf in _tracked_manifests():
        cfg = json.loads(mf.read_text(encoding="utf-8"))["config"]
        if _reconstruct_id(cfg) == _exp_id(mf):
            current_matched.add(_exp_id(mf))
    legacy = [_exp_id(mf) for mf in _tracked_manifests()
              if _exp_id(mf) not in current_matched]
    assert legacy, "期望存在 pre-IMPL-20 legacy 实验（身份记录非重建）"


# ---------------------------------------------------------------------- #
# no absolute path / secret in tracked configs
# ---------------------------------------------------------------------- #

def test_no_absolute_path_or_secret_in_tracked_configs():
    """所有 git-tracked experiments config.yaml + manifest config 不得含
    绝对本地路径 / API key / Authorization / benchmark 私有路径。"""
    offenders = []
    for cf in _tracked_files("experiments/*/*/config.yaml"):
        text = cf.read_text(encoding="utf-8")
        if _ABS_PATH_RE.search(text) or _SECRET_RE.search(text):
            offenders.append(str(cf))
    for mf in _tracked_manifests():
        m = json.loads(mf.read_text(encoding="utf-8"))
        cfg = m.get("config") or {}
        for key, value in cfg.items():
            if isinstance(value, str) and (
                _ABS_PATH_RE.search(value) or _SECRET_RE.search(value)
            ):
                offenders.append(f"{mf}:config.{key}")
    for cf in _tracked_files("config.yaml"):
        text = cf.read_text(encoding="utf-8")
        if _ABS_PATH_RE.search(text) or _SECRET_RE.search(text):
            offenders.append(str(cf))
    assert not offenders, f"tracked configs 含绝对路径/secret: {offenders}"


def test_root_config_yaml_is_clean():
    text = (REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
    assert not _ABS_PATH_RE.search(text)
    assert not _SECRET_RE.search(text)


# ---------------------------------------------------------------------- #
# lock is referenced by a working verifier (thin contract)
# ---------------------------------------------------------------------- #

def test_verify_public_corpus_script_exists_and_imports():
    script = REPO_ROOT / "scripts" / "verify_public_corpus.py"
    assert script.is_file()
    src = script.read_text(encoding="utf-8")
    assert "--data-root" in src
    assert "ExperimentCorpus.build" in src
