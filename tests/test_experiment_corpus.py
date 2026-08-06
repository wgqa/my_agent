"""ExperimentRunner 第四步：ExperimentCorpus 可复现语料清单"""

import hashlib
import subprocess
from pathlib import Path

import pytest

from evaluation.experiment_corpus import ExperimentCorpus


def _make_corpus(tmp_path):
    root = tmp_path / "corpus"
    (root / "project-a").mkdir(parents=True)
    (root / "project-b").mkdir(parents=True)
    (root / "README.md").write_text("# Project\n", encoding="utf-8")
    (root / "project-a" / "app.py").write_text("print(1)\n", encoding="utf-8")
    (root / "project-b" / "notes.txt").write_text("hello world\n", encoding="utf-8")
    return root


def _link_dir(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip("当前平台/权限不支持目录链接")


def test_build_valid_corpus_sorted(tmp_path):
    root = _make_corpus(tmp_path)
    corpus = ExperimentCorpus.build(root, ["project-b/notes.txt", "README.md"])
    assert [e.relative_path for e in corpus.entries] == [
        "README.md", "project-b/notes.txt",
    ]
    assert len(corpus.corpus_id) == 12
    assert all(c in "0123456789abcdef" for c in corpus.corpus_id)


def test_input_order_does_not_change_result(tmp_path):
    root = _make_corpus(tmp_path)
    a = ExperimentCorpus.build(root, ["README.md", "project-a/app.py"])
    b = ExperimentCorpus.build(root, ["project-a/app.py", "README.md"])
    assert [e.relative_path for e in a.entries] == [e.relative_path for e in b.entries]
    assert a.corpus_id == b.corpus_id


def test_content_change_changes_id(tmp_path):
    root = _make_corpus(tmp_path)
    before = ExperimentCorpus.build(root, ["README.md"]).corpus_id
    (root / "README.md").write_text("# Changed\n", encoding="utf-8")
    after = ExperimentCorpus.build(root, ["README.md"]).corpus_id
    assert before != after


def test_path_change_changes_id(tmp_path):
    root = _make_corpus(tmp_path)
    before = ExperimentCorpus.build(root, ["README.md"]).corpus_id
    (root / "README.md").rename(root / "GUIDE.md")
    after = ExperimentCorpus.build(root, ["GUIDE.md"]).corpus_id
    assert before != after


def test_empty_list_rejected(tmp_path):
    root = _make_corpus(tmp_path)
    with pytest.raises(ValueError, match="为空|空"):
        ExperimentCorpus.build(root, [])


def test_duplicate_path_rejected(tmp_path):
    root = _make_corpus(tmp_path)
    with pytest.raises(ValueError, match="重复|dup"):
        ExperimentCorpus.build(root, ["README.md", "./README.md"])


def test_same_basename_different_dirs_rejected(tmp_path):
    root = _make_corpus(tmp_path)
    (root / "project-b" / "README.md").write_text("x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="同名|basename"):
        ExperimentCorpus.build(root, ["README.md", "project-b/README.md"])


def test_absolute_path_rejected(tmp_path):
    root = _make_corpus(tmp_path)
    with pytest.raises(ValueError, match="绝对路径|absolute"):
        ExperimentCorpus.build(root, [str(root / "README.md")])


def test_dotdot_rejected(tmp_path):
    root = _make_corpus(tmp_path)
    with pytest.raises(ValueError, match="穿越|..|dotdot"):
        ExperimentCorpus.build(root, ["../outside.md"])


def test_symlink_escape_rejected(tmp_path):
    root = _make_corpus(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("s", encoding="utf-8")
    _link_dir(root / "escape", outside)
    with pytest.raises(ValueError, match="逃逸|escape"):
        ExperimentCorpus.build(root, ["escape/secret.md"])


def test_unsupported_extension_rejected(tmp_path):
    root = _make_corpus(tmp_path)
    (root / "data.csv").write_text("a,b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="扩展名|ext"):
        ExperimentCorpus.build(root, ["data.csv"])


def test_sha256_matches_direct_bytes(tmp_path):
    root = _make_corpus(tmp_path)
    corpus = ExperimentCorpus.build(root, ["README.md", "project-a/app.py"])
    for entry in corpus.entries:
        full = (root / entry.relative_path).resolve()
        assert entry.sha256 == hashlib.sha256(full.read_bytes()).hexdigest()
        assert entry.size_bytes == full.stat().st_size


# ── corpus_id 无歧义序列化（复审回归） ─────────────────

def test_corpus_id_unambiguous_serialization():
    """未转义分隔符碰撞：两清单旧 payload 相同，修复后 ID 必须不同"""
    from evaluation.experiment_corpus import CorpusEntry
    h1 = "a" * 64
    h2 = "b" * 64
    entries_a = [
        CorpusEntry(relative_path="x", sha256=h1, size_bytes=1),
        CorpusEntry(relative_path="y", sha256=h2, size_bytes=2),
    ]
    entries_b = [
        CorpusEntry(relative_path=f"x:{h1}:1|y", sha256=h2, size_bytes=2),
    ]
    assert ExperimentCorpus._compute_id(entries_a) != ExperimentCorpus._compute_id(
        entries_b
    )


def test_corpus_id_insensitive_to_entry_order_in_compute():
    """_compute_id 内部构造顺序不影响 ID（排序后序列化）"""
    from evaluation.experiment_corpus import CorpusEntry
    e1 = CorpusEntry(relative_path="a", sha256="s1", size_bytes=1)
    e2 = CorpusEntry(relative_path="b", sha256="s2", size_bytes=2)
    assert ExperimentCorpus._compute_id([e1, e2]) == ExperimentCorpus._compute_id(
        [e2, e1]
    )
