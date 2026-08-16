"""Verify the public corpus at an agent_data checkout against the pinned lock.

Read-only. Uses the existing ExperimentCorpus identity logic (no model load, no
Retrieval/LLM/benchmark). Fail-fast on any mismatch:

    python scripts/verify_public_corpus.py --data-root <agent_data checkout>

--data-root must be a wgqa/agent_data checkout whose HEAD equals the pinned
commit in reproducibility/public_data_lock.json. The 37 relative paths come
from the tracked, frozen experiments/*/*/index_manifest.json corpus_entries
(identity already pinned in the main repo). The script then rebuilds the corpus
id over the on-disk files and compares commit/path/file_count/corpus_id.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO_ROOT / "reproducibility" / "public_data_lock.json"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def _load_lock() -> dict:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    for key in ("repository", "commit", "path", "corpus_id", "file_count"):
        if key not in lock:
            _fail(f"public_data_lock.json 缺少字段: {key}")
    return lock


def _git_head(data_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(data_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=20, check=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        _fail(f"--data-root 不是 git checkout: {data_root}")
    return out.stdout.strip()


def _reference_entries() -> list[dict]:
    """Return the frozen 37 corpus_entries from a tracked index_manifest."""
    manifests = sorted(REPO_ROOT.glob("experiments/*/*/index_manifest.json"))
    for mf in manifests:
        m = json.loads(mf.read_text(encoding="utf-8"))
        entries = m.get("corpus_entries")
        if entries:
            return entries
    _fail("未在 tracked experiments/*/*/index_manifest.json 找到 corpus_entries")
    raise AssertionError  # unreachable


def main() -> int:
    from evaluation.experiment_corpus import ExperimentCorpus

    parser = argparse.ArgumentParser(description="Verify pinned public corpus")
    parser.add_argument("--data-root", required=True,
                        help="path to a wgqa/agent_data checkout")
    args = parser.parse_args()

    lock = _load_lock()
    data_root = Path(args.data_root).resolve()
    if not data_root.is_dir():
        _fail(f"--data-root 不是目录: {data_root}")

    # 1) commit pin
    head = _git_head(data_root)
    if head != lock["commit"]:
        _fail(
            f"agent_data HEAD {head} != 锁定 commit {lock['commit']}；"
            f"请 checkout {lock['commit']}"
        )

    # 2) path exists
    corpus_dir = (data_root / lock["path"]).resolve()
    if not corpus_dir.is_dir():
        _fail(f"语料路径不存在: {corpus_dir}")

    # 3) file_count + corpus_id via existing identity logic
    entries = _reference_entries()
    if len(entries) != lock["file_count"]:
        _fail(
            f"参考 corpus_entries={len(entries)} != 锁定 file_count={lock['file_count']}"
        )
    rels = [e["relative_path"] for e in entries]
    corpus = ExperimentCorpus.build(corpus_dir, rels)
    if len(corpus.entries) != lock["file_count"]:
        _fail(f"实际文件数 {len(corpus.entries)} != 锁定 {lock['file_count']}")
    if corpus.corpus_id != lock["corpus_id"]:
        _fail(f"实际 corpus_id {corpus.corpus_id} != 锁定 {lock['corpus_id']}")

    print(f"[OK] corpus verified: commit={head[:7]} path={lock['path']} "
          f"file_count={len(corpus.entries)} corpus_id={corpus.corpus_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
