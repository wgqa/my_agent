"""Tests for Gate 3 evaluation set strong-typed contract (G3-DATA-02A).

Covers: load_jsonl strict parsing, answerability cross-field invariants,
stable evaluation_set_id, and path normalization. Uses tmp_path with a
synthetic corpus and synthetic JSONL only; never reads real benchmarks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.gate3 import (
    GATE3_CASE_SCHEMA_VERSION,
    GATE3_EVALUATION_SET_SCHEMA_VERSION,
    EvidenceObligation,
    Gate3Case,
    Gate3EvaluationSet,
)


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _write_corpus(tmp_path: Path) -> ExperimentCorpus:
    """Write a synthetic 4-file corpus and build an ExperimentCorpus."""
    root = tmp_path / "corpus"
    files = {
        "core/pipeline.py": "def build():\n    pass\n",
        "core/retriever/hybrid.py": "class HybridRetriever:\n    pass\n",
        "docs/x.md": "# X\nsome markdown\n",
        "rag/文档处理.md": "# 文档处理\n内容\n",
    }
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return ExperimentCorpus.build(root, list(files.keys()))


def _write_jsonl(path: Path, cases: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def _case(**overrides: object) -> dict:
    """Default valid answerable case; merge overrides on top."""
    base: dict = {
        "schema_version": GATE3_CASE_SCHEMA_VERSION,
        "case_id": "g3q001",
        "query": "对比 Pipeline 与 Hybrid 两个组件的差异",
        "query_type": "comparison",
        "answerability": "answerable",
        "decomposition_expected": "required",
        "retrieval_required": True,
        "evidence_obligations": [
            {
                "obligation_id": "o1",
                "description": "需要 Pipeline 相关证据",
                "relevant_files": ["core/pipeline.py"],
                "required": True,
            },
            {
                "obligation_id": "o2",
                "description": "需要 Hybrid 相关证据",
                "relevant_files": ["core/retriever/hybrid.py"],
                "required": True,
            },
        ],
        "relevant_files": [
            "core/retriever/hybrid.py",
            "core/pipeline.py",
        ],
        "tags": ["comparison"],
    }
    base.update(overrides)
    return base


def _write_default(tmp_path: Path) -> tuple[ExperimentCorpus, Path]:
    corpus = _write_corpus(tmp_path)
    path = tmp_path / "set.jsonl"
    _write_jsonl(path, [_case()])
    return corpus, path


# ---------------------------------------------------------------------------
# normal path
# ---------------------------------------------------------------------------


class TestNormalPath:
    def test_loads_single_answerable_case(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        s = Gate3EvaluationSet.load_jsonl(path, corpus)
        assert len(s.cases) == 1
        c = s.cases[0]
        assert isinstance(c, Gate3Case)
        assert c.case_id == "g3q001"
        assert c.schema_version == GATE3_CASE_SCHEMA_VERSION
        assert c.answerability == "answerable"
        assert c.retrieval_required is True
        assert c.query_type == "comparison"
        assert c.decomposition_expected == "required"
        assert [o.obligation_id for o in c.evidence_obligations] == ["o1", "o2"]
        assert all(isinstance(o, EvidenceObligation) for o in c.evidence_obligations)
        assert c.relevant_files == ("core/pipeline.py", "core/retriever/hybrid.py")
        assert c.tags == ("comparison",)

    def test_loads_multiple_cases_sorted_by_case_id(self, tmp_path):
        corpus = _write_corpus(tmp_path)
        path = tmp_path / "set.jsonl"
        cases = [
            _case(case_id="g3q002", query="第二个问题"),
            _case(case_id="g3q001", query="第一个问题"),
            _case(case_id="g3q010", query="第十个问题"),
        ]
        _write_jsonl(path, cases)
        s = Gate3EvaluationSet.load_jsonl(path, corpus)
        assert [c.case_id for c in s.cases] == ["g3q001", "g3q002", "g3q010"]

    def test_evidence_obligations_sorted_by_obligation_id(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        cases = [
            _case(
                evidence_obligations=[
                    {
                        "obligation_id": "o2",
                        "description": "Hybrid",
                        "relevant_files": ["core/retriever/hybrid.py"],
                        "required": True,
                    },
                    {
                        "obligation_id": "o1",
                        "description": "Pipeline",
                        "relevant_files": ["core/pipeline.py"],
                        "required": True,
                    },
                ]
            )
        ]
        _write_jsonl(path, cases)
        s = Gate3EvaluationSet.load_jsonl(path, corpus)
        c = s.cases[0]
        assert [o.obligation_id for o in c.evidence_obligations] == ["o1", "o2"]

    def test_blank_lines_ignored(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        with path.open("w", encoding="utf-8") as f:
            f.write("\n")
            f.write(json.dumps(_case(), ensure_ascii=False) + "\n")
            f.write("   \n")
            f.write("\n")
        s = Gate3EvaluationSet.load_jsonl(path, corpus)
        assert len(s.cases) == 1

    def test_backslash_and_dotdot_normalized_to_posix(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case(
            evidence_obligations=[
                {
                    "obligation_id": "o1",
                    "description": "docs",
                    "relevant_files": [r"docs\x.md"],
                    "required": True,
                }
            ],
            relevant_files=["docs/./x.md"],
        )
        _write_jsonl(path, [c])
        s = Gate3EvaluationSet.load_jsonl(path, corpus)
        assert s.cases[0].relevant_files == ("docs/x.md",)

    def test_duplicate_relevant_files_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case(
            evidence_obligations=[
                {
                    "obligation_id": "o1",
                    "description": "dup",
                    "relevant_files": ["core/pipeline.py", "core/pipeline.py"],
                    "required": True,
                }
            ],
            relevant_files=["core/pipeline.py", "core/pipeline.py"],
        )
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "重复" in str(ei.value)

    def test_tags_sorted_deduped(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case(tags=["b", "a", "b"])
        _write_jsonl(path, [c])
        s = Gate3EvaluationSet.load_jsonl(path, corpus)
        assert s.cases[0].tags == ("a", "b")

    def test_evaluation_set_schema_version_and_id(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        s = Gate3EvaluationSet.load_jsonl(path, corpus)
        assert s.schema_version == GATE3_EVALUATION_SET_SCHEMA_VERSION
        assert s.corpus_id == corpus.corpus_id
        assert len(s.evaluation_set_id) == 12

    def test_to_dict_deep_isolated(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        s = Gate3EvaluationSet.load_jsonl(path, corpus)
        d = s.to_dict()
        assert d["schema_version"] == GATE3_EVALUATION_SET_SCHEMA_VERSION
        assert d["corpus_id"] == corpus.corpus_id
        assert len(d["cases"]) == 1
        assert "evaluation_set_id" not in d
        case0 = d["cases"][0]
        assert case0["case_id"] == "g3q001"
        assert case0["evidence_obligations"][0]["obligation_id"] == "o1"

    def test_case_to_dict_roundtrip_fields(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        s = Gate3EvaluationSet.load_jsonl(path, corpus)
        c = s.cases[0]
        d = c.to_dict()
        assert d["schema_version"] == GATE3_CASE_SCHEMA_VERSION
        assert d["query"] == c.query
        assert d["query_type"] == "comparison"
        assert d["answerability"] == "answerable"
        assert d["decomposition_expected"] == "required"
        assert d["retrieval_required"] is True
        assert len(d["evidence_obligations"]) == 2
        assert d["relevant_files"] == list(c.relevant_files)
        assert d["tags"] == ["comparison"]
        assert "plan_id" not in d

    def test_obligation_to_dict_fields(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        s = Gate3EvaluationSet.load_jsonl(path, corpus)
        o = s.cases[0].evidence_obligations[0]
        d = o.to_dict()
        assert d["obligation_id"] == "o1"
        assert d["description"] == "需要 Pipeline 相关证据"
        assert d["relevant_files"] == ["core/pipeline.py"]
        assert d["required"] is True

    def test_empty_file_is_valid_empty_set(self, tmp_path):
        corpus = _write_corpus(tmp_path)
        path = tmp_path / "set.jsonl"
        path.write_text("", encoding="utf-8")
        s = Gate3EvaluationSet.load_jsonl(path, corpus)
        assert s.cases == ()
        assert len(s.evaluation_set_id) == 12


# ---------------------------------------------------------------------------
# identity stability
# ---------------------------------------------------------------------------


class TestIdentityStability:
    def test_id_stable_across_case_order(self, tmp_path):
        corpus = _write_corpus(tmp_path)
        path1 = tmp_path / "a.jsonl"
        path2 = tmp_path / "b.jsonl"
        c1 = _case(case_id="g3q001", query="第一个问题")
        c2 = _case(case_id="g3q002", query="第二个问题")
        _write_jsonl(path1, [c1, c2])
        _write_jsonl(path2, [c2, c1])
        a = Gate3EvaluationSet.load_jsonl(path1, corpus)
        b = Gate3EvaluationSet.load_jsonl(path2, corpus)
        assert a.evaluation_set_id == b.evaluation_set_id

    def test_id_stable_across_backslash_vs_forward_slash(self, tmp_path):
        corpus = _write_corpus(tmp_path)
        path1 = tmp_path / "a.jsonl"
        path2 = tmp_path / "b.jsonl"
        _write_jsonl(path1, [_case(relevant_files=[r"core\pipeline.py", "core/retriever/hybrid.py"])])
        _write_jsonl(path2, [_case(relevant_files=["core/pipeline.py", "core/retriever/hybrid.py"])])
        a = Gate3EvaluationSet.load_jsonl(path1, corpus)
        b = Gate3EvaluationSet.load_jsonl(path2, corpus)
        assert a.evaluation_set_id == b.evaluation_set_id

    def test_id_stable_across_field_ordering_in_json(self, tmp_path):
        corpus = _write_corpus(tmp_path)
        path1 = tmp_path / "a.jsonl"
        path2 = tmp_path / "b.jsonl"
        ordered = _case()
        shuffled = {
            "tags": ordered["tags"],
            "case_id": ordered["case_id"],
            "query": ordered["query"],
            "answerability": ordered["answerability"],
            "decomposition_expected": ordered["decomposition_expected"],
            "schema_version": ordered["schema_version"],
            "retrieval_required": ordered["retrieval_required"],
            "query_type": ordered["query_type"],
            "evidence_obligations": ordered["evidence_obligations"],
            "relevant_files": ordered["relevant_files"],
        }
        _write_jsonl(path1, [ordered])
        _write_jsonl(path2, [shuffled])
        a = Gate3EvaluationSet.load_jsonl(path1, corpus)
        b = Gate3EvaluationSet.load_jsonl(path2, corpus)
        assert a.evaluation_set_id == b.evaluation_set_id

    def test_id_stable_across_obligation_order(self, tmp_path):
        corpus = _write_corpus(tmp_path)
        path1 = tmp_path / "a.jsonl"
        path2 = tmp_path / "b.jsonl"
        c1 = _case()
        c2 = _case(
            evidence_obligations=list(reversed(c1["evidence_obligations"]))
        )
        _write_jsonl(path1, [c1])
        _write_jsonl(path2, [c2])
        a = Gate3EvaluationSet.load_jsonl(path1, corpus)
        b = Gate3EvaluationSet.load_jsonl(path2, corpus)
        assert a.evaluation_set_id == b.evaluation_set_id

    def test_id_stable_across_relevant_files_order(self, tmp_path):
        corpus = _write_corpus(tmp_path)
        path1 = tmp_path / "a.jsonl"
        path2 = tmp_path / "b.jsonl"
        _write_jsonl(path1, [_case(relevant_files=["core/pipeline.py", "core/retriever/hybrid.py"])])
        _write_jsonl(path2, [_case(relevant_files=["core/retriever/hybrid.py", "core/pipeline.py"])])
        a = Gate3EvaluationSet.load_jsonl(path1, corpus)
        b = Gate3EvaluationSet.load_jsonl(path2, corpus)
        assert a.evaluation_set_id == b.evaluation_set_id

    def test_id_stable_across_tags_order(self, tmp_path):
        corpus = _write_corpus(tmp_path)
        path1 = tmp_path / "a.jsonl"
        path2 = tmp_path / "b.jsonl"
        _write_jsonl(path1, [_case(tags=["a", "b"])])
        _write_jsonl(path2, [_case(tags=["b", "a"])])
        a = Gate3EvaluationSet.load_jsonl(path1, corpus)
        b = Gate3EvaluationSet.load_jsonl(path2, corpus)
        assert a.evaluation_set_id == b.evaluation_set_id

    def test_id_changes_when_query_changes(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        a = Gate3EvaluationSet.load_jsonl(path, corpus)
        path2 = tmp_path / "b.jsonl"
        _write_jsonl(path2, [_case(query="完全不同的另一个问题")])
        b = Gate3EvaluationSet.load_jsonl(path2, corpus)
        assert a.evaluation_set_id != b.evaluation_set_id

    def test_id_changes_when_obligation_description_changes(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        a = Gate3EvaluationSet.load_jsonl(path, corpus)
        path2 = tmp_path / "b.jsonl"
        c = _case()
        c["evidence_obligations"][0]["description"] = "改了描述"
        _write_jsonl(path2, [c])
        b = Gate3EvaluationSet.load_jsonl(path2, corpus)
        assert a.evaluation_set_id != b.evaluation_set_id

    def test_id_changes_when_obligation_required_flag_changes(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        a = Gate3EvaluationSet.load_jsonl(path, corpus)
        path2 = tmp_path / "b.jsonl"
        c = _case()
        c["evidence_obligations"][0]["required"] = False
        _write_jsonl(path2, [c])
        b = Gate3EvaluationSet.load_jsonl(path2, corpus)
        assert a.evaluation_set_id != b.evaluation_set_id

    def test_id_changes_when_answerability_changes(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        a = Gate3EvaluationSet.load_jsonl(path, corpus)
        path2 = tmp_path / "b.jsonl"
        _write_jsonl(path2, [_case(answerability="unanswerable", query_type="unanswerable_or_no_retrieval", evidence_obligations=[], relevant_files=[], decomposition_expected="forbidden")])
        b = Gate3EvaluationSet.load_jsonl(path2, corpus)
        assert a.evaluation_set_id != b.evaluation_set_id

    def test_id_changes_when_retrieval_required_changes(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        a = Gate3EvaluationSet.load_jsonl(path, corpus)
        path2 = tmp_path / "b.jsonl"
        _write_jsonl(path2, [_case(retrieval_required=False, answerability="no_retrieval", query_type="unanswerable_or_no_retrieval", evidence_obligations=[], relevant_files=[], decomposition_expected="forbidden")])
        b = Gate3EvaluationSet.load_jsonl(path2, corpus)
        assert a.evaluation_set_id != b.evaluation_set_id

    def test_id_changes_when_duplicate_case_removed(self, tmp_path):
        corpus = _write_corpus(tmp_path)
        path1 = tmp_path / "a.jsonl"
        path2 = tmp_path / "b.jsonl"
        _write_jsonl(path1, [
            _case(case_id="g3q001", query="第一个问题"),
            _case(case_id="g3q002", query="第二个问题"),
        ])
        _write_jsonl(path2, [_case(case_id="g3q001", query="第一个问题")])
        a = Gate3EvaluationSet.load_jsonl(path1, corpus)
        b = Gate3EvaluationSet.load_jsonl(path2, corpus)
        assert a.evaluation_set_id != b.evaluation_set_id


# ---------------------------------------------------------------------------
# strict parsing
# ---------------------------------------------------------------------------


class TestStrictParsing:
    def test_missing_file_raises(self, tmp_path):
        corpus = _write_corpus(tmp_path)
        with pytest.raises(FileNotFoundError):
            Gate3EvaluationSet.load_jsonl(tmp_path / "nope.jsonl", corpus)

    def test_path_is_directory_raises(self, tmp_path):
        corpus = _write_corpus(tmp_path)
        with pytest.raises(Exception):
            Gate3EvaluationSet.load_jsonl(tmp_path, corpus)

    def test_malformed_json_raises_with_lineno(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        with path.open("a", encoding="utf-8") as f:
            f.write("{not json\n")
        with pytest.raises(ValueError) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "2" in str(ei.value)

    def test_non_dict_line_raises(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        with path.open("a", encoding="utf-8") as f:
            f.write("[1,2,3]\n")
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "JSON object" in str(ei.value)

    def test_unknown_top_level_field_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        c["bogus_field"] = 1
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "bogus_field" in str(ei.value)

    def test_missing_top_level_field_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        del c["query_type"]
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "query_type" in str(ei.value)

    def test_missing_schema_version_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        del c["schema_version"]
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "schema_version" in str(ei.value)

    def test_wrong_schema_version_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(schema_version="gate3_case_v999")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "gate3_case_v999" in str(ei.value)

    def test_case_id_wrong_format_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(case_id="case_001")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "g3q001" in str(ei.value) or "case_id" in str(ei.value)

    def test_case_id_non_string_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(case_id=123)])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "case_id" in str(ei.value)

    def test_query_non_string_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(query=42)])
        with pytest.raises(Exception):
            Gate3EvaluationSet.load_jsonl(path, corpus)

    def test_query_empty_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(query="")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "query" in str(ei.value)

    def test_query_not_stripped_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(query="  对比差异  ")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "query" in str(ei.value)

    def test_query_too_long_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(query="x" * 4001)])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "4000" in str(ei.value)

    def test_query_duplicate_rejected(self, tmp_path):
        corpus = _write_corpus(tmp_path)
        path = tmp_path / "set.jsonl"
        _write_jsonl(path, [_case(case_id="g3q001"), _case(case_id="g3q002")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "g3q002" in str(ei.value)

    def test_duplicate_case_id_rejected(self, tmp_path):
        corpus = _write_corpus(tmp_path)
        path = tmp_path / "set.jsonl"
        _write_jsonl(path, [_case(case_id="g3q001"), _case(case_id="g3q001", query="另一个问题")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "g3q001" in str(ei.value)

    def test_query_type_unknown_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(query_type="mystery")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "mystery" in str(ei.value)

    def test_query_type_non_string_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(query_type=5)])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "query_type" in str(ei.value)

    def test_answerability_unknown_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(answerability="maybe")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "maybe" in str(ei.value)

    def test_decomposition_expected_unknown_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(decomposition_expected="sometimes")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "sometimes" in str(ei.value)

    def test_retrieval_required_int_1_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(retrieval_required=1)])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "bool" in str(ei.value) or "retrieval_required" in str(ei.value)

    def test_retrieval_required_string_true_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(retrieval_required="true")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "bool" in str(ei.value) or "retrieval_required" in str(ei.value)

    def test_obligation_unknown_field_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        c["evidence_obligations"][0]["extra"] = 1
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "extra" in str(ei.value)

    def test_obligation_missing_field_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        del c["evidence_obligations"][0]["description"]
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "description" in str(ei.value)

    def test_obligation_id_gap_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        c["evidence_obligations"].append(
            {
                "obligation_id": "o4",
                "description": "o4",
                "relevant_files": ["docs/x.md"],
                "required": True,
            }
        )
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "o3" in str(ei.value)

    def test_obligation_id_wrong_format_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        c["evidence_obligations"][0]["obligation_id"] = "ob1"
        _write_jsonl(path, [c])
        with pytest.raises(Exception):
            Gate3EvaluationSet.load_jsonl(path, corpus)

    def test_obligation_id_duplicate_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        c["evidence_obligations"][0]["obligation_id"] = "o2"
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "o2" in str(ei.value)

    def test_obligation_description_empty_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        c["evidence_obligations"][0]["description"] = ""
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "description" in str(ei.value)

    def test_obligation_description_too_long_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        c["evidence_obligations"][0]["description"] = "x" * 501
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "500" in str(ei.value)

    def test_obligation_required_int_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        c["evidence_obligations"][0]["required"] = 1
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "required" in str(ei.value)

    def test_obligation_relevant_files_empty_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        c["evidence_obligations"][0]["relevant_files"] = []
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "relevant_files" in str(ei.value)

    def test_relevant_files_non_list_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(relevant_files="core/pipeline.py")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "relevant_files" in str(ei.value)

    def test_relevant_files_not_in_corpus_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(relevant_files=["core/elsewhere.py"])])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "elsewhere.py" in str(ei.value)

    def test_absolute_path_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(relevant_files=["C:/core/pipeline.py"])])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "C:" in str(ei.value)

    def test_windows_style_path_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(relevant_files=[r"C:\core\pipeline.py"])])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "C:" in str(ei.value)

    def test_dotdot_path_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(relevant_files=["core/../core/pipeline.py"])])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert ".." in str(ei.value)

    def test_leading_slash_path_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(relevant_files=["/core/pipeline.py"])])
        with pytest.raises(Exception):
            Gate3EvaluationSet.load_jsonl(path, corpus)

    def test_unc_path_rejected(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(relevant_files=["//server/share/core/pipeline.py"])])
        with pytest.raises(Exception):
            Gate3EvaluationSet.load_jsonl(path, corpus)

    def test_error_message_includes_lineno_and_case_id(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(_case(case_id="g3q002", query_type="bogus"), ensure_ascii=False) + "\n")
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        msg = str(ei.value)
        assert "2" in msg
        assert "g3q002" in msg


# ---------------------------------------------------------------------------
# answerability cross-field invariants
# ---------------------------------------------------------------------------


class TestAnswerabilityInvariants:
    def test_answerable_needs_nonempty_obligations(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(evidence_obligations=[], relevant_files=[])])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "evidence_obligations" in str(ei.value)

    def test_answerable_requires_at_least_one_required_obligation(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        c["evidence_obligations"][0]["required"] = False
        c["evidence_obligations"][1]["required"] = False
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "required" in str(ei.value)

    def test_answerable_top_level_must_equal_union(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        c = _case()
        c["relevant_files"] = ["core/pipeline.py"]  # missing hybrid
        _write_jsonl(path, [c])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "relevant_files" in str(ei.value)

    def test_answerable_cannot_be_unanswerable_query_type(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(query_type="unanswerable_or_no_retrieval")])
        with pytest.raises(Exception):
            Gate3EvaluationSet.load_jsonl(path, corpus)

    def test_answerable_requires_retrieval_true(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(retrieval_required=False)])
        with pytest.raises(Exception):
            Gate3EvaluationSet.load_jsonl(path, corpus)

    def test_unanswerable_must_have_empty_obligations(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(answerability="unanswerable", query_type="unanswerable_or_no_retrieval", decomposition_expected="forbidden")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "evidence_obligations" in str(ei.value)

    def test_unanswerable_must_have_empty_relevant_files(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(answerability="unanswerable", query_type="unanswerable_or_no_retrieval", evidence_obligations=[], decomposition_expected="forbidden", relevant_files=["core/pipeline.py"])])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "relevant_files" in str(ei.value)

    def test_unanswerable_must_be_forbidden_decomposition(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(answerability="unanswerable", query_type="unanswerable_or_no_retrieval", evidence_obligations=[], relevant_files=[], decomposition_expected="required")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "forbidden" in str(ei.value)

    def test_unanswerable_requires_retrieval_true(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(answerability="unanswerable", query_type="unanswerable_or_no_retrieval", evidence_obligations=[], relevant_files=[], decomposition_expected="forbidden", retrieval_required=False)])
        with pytest.raises(Exception):
            Gate3EvaluationSet.load_jsonl(path, corpus)

    def test_no_retrieval_must_have_empty_obligations(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(answerability="no_retrieval", query_type="unanswerable_or_no_retrieval", decomposition_expected="forbidden", retrieval_required=False)])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "evidence_obligations" in str(ei.value)

    def test_no_retrieval_must_be_forbidden_decomposition(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(answerability="no_retrieval", query_type="unanswerable_or_no_retrieval", evidence_obligations=[], relevant_files=[], retrieval_required=False, decomposition_expected="optional")])
        with pytest.raises(Exception) as ei:
            Gate3EvaluationSet.load_jsonl(path, corpus)
        assert "forbidden" in str(ei.value)

    def test_no_retrieval_requires_retrieval_false(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(answerability="no_retrieval", query_type="unanswerable_or_no_retrieval", evidence_obligations=[], relevant_files=[], decomposition_expected="forbidden", retrieval_required=True)])
        with pytest.raises(Exception):
            Gate3EvaluationSet.load_jsonl(path, corpus)

    def test_no_retrieval_must_be_unanswerable_query_type(self, tmp_path):
        corpus, path = _write_default(tmp_path)
        _write_jsonl(path, [_case(answerability="no_retrieval", query_type="fact", evidence_obligations=[], relevant_files=[], decomposition_expected="forbidden", retrieval_required=False)])
        with pytest.raises(Exception):
            Gate3EvaluationSet.load_jsonl(path, corpus)
