"""G2-EVAL-06：可复现 RetrievalEvaluationSet（JSONL 严格解析与稳定 ID）"""

import dataclasses
import json

import pytest

from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.retrieval_evaluation_set import RetrievalCase, RetrievalEvaluationSet


def _make_corpus(tmp_path):
    root = tmp_path / "corpus"
    (root / "core" / "retriever").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "core" / "pipeline.py").write_text("def p(): pass\n", encoding="utf-8")
    (root / "core" / "retriever" / "hybrid.py").write_text(
        "def h(): pass\n", encoding="utf-8"
    )
    (root / "docs" / "x.md").write_text("# X\n", encoding="utf-8")
    return ExperimentCorpus.build(
        root,
        ["core/pipeline.py", "core/retriever/hybrid.py", "docs/x.md"],
    )


def _write_jsonl(tmp_path, rows, name="cases.jsonl"):
    path = tmp_path / name
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")
    return path


def _rows():
    return [
        {
            "case_id": "q002",
            "query": "BM25 索引在哪里重建？",
            "relevant_files": ["core/retriever/hybrid.py"],
        },
        {
            "case_id": "q001",
            "query": "Pipeline 如何串联？",
            "relevant_files": ["core/pipeline.py", "docs/x.md"],
        },
    ]


def test_load_normal_multiple_cases(tmp_path):
    corpus = _make_corpus(tmp_path)
    path = _write_jsonl(tmp_path, _rows())
    evalset = RetrievalEvaluationSet.load_jsonl(path, corpus)
    assert evalset.corpus_id == corpus.corpus_id
    assert len(evalset.cases) == 2
    assert evalset.cases[0].case_id == "q001"
    assert evalset.cases[0].query == "Pipeline 如何串联？"
    assert evalset.cases[0].relevant_files == ("core/pipeline.py", "docs/x.md")
    assert len(evalset.evaluation_set_id) == 12
    assert all(c in "0123456789abcdef" for c in evalset.evaluation_set_id)


def test_cases_sorted_by_case_id(tmp_path):
    corpus = _make_corpus(tmp_path)
    path = _write_jsonl(tmp_path, _rows())
    evalset = RetrievalEvaluationSet.load_jsonl(path, corpus)
    assert [c.case_id for c in evalset.cases] == ["q001", "q002"]


def test_relevant_files_normalized_sorted(tmp_path):
    corpus = _make_corpus(tmp_path)
    rows = [{
        "case_id": "q001",
        "query": "query",
        "relevant_files": ["./docs/x.md", "core/pipeline.py"],
    }]
    path = _write_jsonl(tmp_path, rows)
    evalset = RetrievalEvaluationSet.load_jsonl(path, corpus)
    assert evalset.cases[0].relevant_files == ("core/pipeline.py", "docs/x.md")


def test_jsonl_line_order_same_id(tmp_path):
    corpus = _make_corpus(tmp_path)
    rows = _rows()
    a = RetrievalEvaluationSet.load_jsonl(_write_jsonl(tmp_path, rows, "a.jsonl"), corpus)
    b = RetrievalEvaluationSet.load_jsonl(
        _write_jsonl(tmp_path, list(reversed(rows)), "b.jsonl"), corpus
    )
    assert a.evaluation_set_id == b.evaluation_set_id


def test_relevant_files_input_order_same_id(tmp_path):
    corpus = _make_corpus(tmp_path)
    base = {
        "case_id": "q001",
        "query": "query",
        "relevant_files": ["docs/x.md", "core/pipeline.py"],
    }
    swapped = dict(base, relevant_files=["core/pipeline.py", "docs/x.md"])
    a = RetrievalEvaluationSet.load_jsonl(_write_jsonl(tmp_path, [base], "a.jsonl"), corpus)
    b = RetrievalEvaluationSet.load_jsonl(
        _write_jsonl(tmp_path, [swapped], "b.jsonl"), corpus
    )
    assert a.evaluation_set_id == b.evaluation_set_id


def test_query_change_changes_id(tmp_path):
    corpus = _make_corpus(tmp_path)
    rows = [{
        "case_id": "q001",
        "query": "原始查询",
        "relevant_files": ["docs/x.md"],
    }]
    changed = [dict(rows[0], query="修改后的查询")]
    a = RetrievalEvaluationSet.load_jsonl(_write_jsonl(tmp_path, rows, "a.jsonl"), corpus)
    b = RetrievalEvaluationSet.load_jsonl(
        _write_jsonl(tmp_path, changed, "b.jsonl"), corpus
    )
    assert a.evaluation_set_id != b.evaluation_set_id


def test_relevant_files_change_changes_id(tmp_path):
    corpus = _make_corpus(tmp_path)
    rows = [{
        "case_id": "q001",
        "query": "query",
        "relevant_files": ["docs/x.md"],
    }]
    changed = [dict(rows[0], relevant_files=["docs/x.md", "core/pipeline.py"])]
    a = RetrievalEvaluationSet.load_jsonl(_write_jsonl(tmp_path, rows, "a.jsonl"), corpus)
    b = RetrievalEvaluationSet.load_jsonl(
        _write_jsonl(tmp_path, changed, "b.jsonl"), corpus
    )
    assert a.evaluation_set_id != b.evaluation_set_id


def test_corpus_id_change_changes_id(tmp_path):
    corpus = _make_corpus(tmp_path)
    rows = _rows()
    path = _write_jsonl(tmp_path, rows)
    first = RetrievalEvaluationSet.load_jsonl(path, corpus)

    (corpus.corpus_root / "docs" / "x.md").write_text("# X changed\n", encoding="utf-8")
    changed_corpus = ExperimentCorpus.build(
        corpus.corpus_root,
        ["core/pipeline.py", "core/retriever/hybrid.py", "docs/x.md"],
    )
    assert changed_corpus.corpus_id != corpus.corpus_id
    second = RetrievalEvaluationSet.load_jsonl(path, changed_corpus)
    assert first.evaluation_set_id != second.evaluation_set_id


def test_duplicate_case_id_rejected(tmp_path):
    corpus = _make_corpus(tmp_path)
    rows = [
        {"case_id": "q001", "query": "a", "relevant_files": ["docs/x.md"]},
        {"case_id": "q001", "query": "b", "relevant_files": ["core/pipeline.py"]},
    ]
    path = _write_jsonl(tmp_path, rows)
    with pytest.raises(ValueError, match="重复"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


def test_duplicate_query_rejected(tmp_path):
    corpus = _make_corpus(tmp_path)
    rows = [
        {"case_id": "q001", "query": "相同问题", "relevant_files": ["docs/x.md"]},
        {"case_id": "q002", "query": "相同问题", "relevant_files": ["core/pipeline.py"]},
    ]
    path = _write_jsonl(tmp_path, rows)
    with pytest.raises(ValueError, match="重复"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


@pytest.mark.parametrize("query", ["", "   ", "\t\n"])
def test_query_empty_or_whitespace_only_rejected(tmp_path, query):
    corpus = _make_corpus(tmp_path)
    rows = [{"case_id": "q001", "query": query, "relevant_files": ["docs/x.md"]}]
    path = _write_jsonl(tmp_path, rows)
    with pytest.raises(ValueError, match="空|空白"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


@pytest.mark.parametrize("query", [" query", "query ", "\tquery"])
def test_query_leading_trailing_whitespace_rejected(tmp_path, query):
    corpus = _make_corpus(tmp_path)
    rows = [{"case_id": "q001", "query": query, "relevant_files": ["docs/x.md"]}]
    path = _write_jsonl(tmp_path, rows)
    with pytest.raises(ValueError, match="首尾|空白"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


def test_empty_relevant_files_rejected(tmp_path):
    corpus = _make_corpus(tmp_path)
    rows = [{"case_id": "q001", "query": "query", "relevant_files": []}]
    path = _write_jsonl(tmp_path, rows)
    with pytest.raises(ValueError, match="relevant_files|不能为空"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


def test_duplicate_relevant_path_rejected(tmp_path):
    corpus = _make_corpus(tmp_path)
    rows = [{
        "case_id": "q001",
        "query": "query",
        "relevant_files": ["docs/x.md", "./docs/x.md"],
    }]
    path = _write_jsonl(tmp_path, rows)
    with pytest.raises(ValueError, match="重复"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


def test_relevant_path_not_in_corpus_rejected(tmp_path):
    corpus = _make_corpus(tmp_path)
    rows = [{
        "case_id": "q001",
        "query": "query",
        "relevant_files": ["docs/x.md", "docs/unknown.md"],
    }]
    path = _write_jsonl(tmp_path, rows)
    with pytest.raises(ValueError, match="第 1 行|q001|不属于 ExperimentCorpus|docs/unknown.md"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


@pytest.mark.parametrize("bad", [
    "/etc/passwd",
    "C:/x.md",
    "C:\\x.md",
    "//server/share/x.md",
    "..",
    "../x.md",
    "a/../b.md",
])
def test_absolute_and_dotdot_paths_rejected(tmp_path, bad):
    corpus = _make_corpus(tmp_path)
    rows = [{"case_id": "q001", "query": "query", "relevant_files": [bad]}]
    path = _write_jsonl(tmp_path, rows)
    with pytest.raises(ValueError, match="绝对|穿越|\\.\\."):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


def test_unknown_field_rejected(tmp_path):
    corpus = _make_corpus(tmp_path)
    rows = [{
        "case_id": "q001",
        "query": "query",
        "relevant_files": ["docs/x.md"],
        "answer": "not allowed",
    }]
    path = _write_jsonl(tmp_path, rows)
    with pytest.raises(ValueError, match="未知字段|answer"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


@pytest.mark.parametrize("missing", ["case_id", "query", "relevant_files"])
def test_missing_field_rejected(tmp_path, missing):
    corpus = _make_corpus(tmp_path)
    row = {
        "case_id": "q001",
        "query": "query",
        "relevant_files": ["docs/x.md"],
    }
    row.pop(missing)
    path = _write_jsonl(tmp_path, [row])
    with pytest.raises(ValueError, match="缺少字段|" + missing):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


def test_invalid_json_includes_line_number(tmp_path):
    corpus = _make_corpus(tmp_path)
    lines = [
        json.dumps(_rows()[0], ensure_ascii=False),
        json.dumps(_rows()[1], ensure_ascii=False),
        "{ this is not valid json",
    ]
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="第 3 行"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


def test_non_object_line_rejected(tmp_path):
    corpus = _make_corpus(tmp_path)
    lines = [
        json.dumps(_rows()[0], ensure_ascii=False),
        "[1, 2, 3]",
    ]
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="第 2 行|object"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


@pytest.mark.parametrize("value", [123, True, None])
def test_non_string_case_id_rejected(tmp_path, value):
    corpus = _make_corpus(tmp_path)
    rows = [{"case_id": value, "query": "query", "relevant_files": ["docs/x.md"]}]
    path = _write_jsonl(tmp_path, rows)
    with pytest.raises(ValueError, match="case_id|字符串"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


@pytest.mark.parametrize("value", [123, True, None])
def test_non_string_query_rejected(tmp_path, value):
    corpus = _make_corpus(tmp_path)
    rows = [{"case_id": "q001", "query": value, "relevant_files": ["docs/x.md"]}]
    path = _write_jsonl(tmp_path, rows)
    with pytest.raises(ValueError, match="query|字符串"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


@pytest.mark.parametrize("value", [123, True, None])
def test_non_string_relevant_path_rejected(tmp_path, value):
    corpus = _make_corpus(tmp_path)
    rows = [{"case_id": "q001", "query": "query", "relevant_files": [value]}]
    path = _write_jsonl(tmp_path, rows)
    with pytest.raises(ValueError, match="relevant_files|字符串"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


def test_unicode_and_emoji_queries_stable(tmp_path):
    corpus = _make_corpus(tmp_path)
    query = "中文查询 query with 🚀 emoji"
    rows = [{"case_id": "q001", "query": query, "relevant_files": ["docs/x.md"]}]
    a = RetrievalEvaluationSet.load_jsonl(_write_jsonl(tmp_path, rows, "a.jsonl"), corpus)
    b = RetrievalEvaluationSet.load_jsonl(_write_jsonl(tmp_path, rows, "b.jsonl"), corpus)
    assert a.cases[0].query == query
    assert a.evaluation_set_id == b.evaluation_set_id
    assert len(a.evaluation_set_id) == 12
    assert all(c in "0123456789abcdef" for c in a.evaluation_set_id)


def test_models_are_immutable():
    case = RetrievalCase(case_id="q1", query="q", relevant_files=("a",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        case.case_id = "x"
    with pytest.raises(dataclasses.FrozenInstanceError):
        case.relevant_files = ("b",)

    evalset = RetrievalEvaluationSet(
        corpus_id="corpus", cases=(case,), evaluation_set_id="id"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        evalset.cases = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        evalset.evaluation_set_id = "other"


def test_missing_file_rejected(tmp_path):
    corpus = _make_corpus(tmp_path)
    with pytest.raises(FileNotFoundError):
        RetrievalEvaluationSet.load_jsonl(tmp_path / "missing.jsonl", corpus)


def test_path_not_file_rejected(tmp_path):
    corpus = _make_corpus(tmp_path)
    with pytest.raises(ValueError, match="不是文件|文件"):
        RetrievalEvaluationSet.load_jsonl(tmp_path, corpus)


def test_empty_file_rejected(tmp_path):
    corpus = _make_corpus(tmp_path)
    path = _write_jsonl(tmp_path, [])
    with pytest.raises(ValueError, match="空"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


def test_only_blank_lines_rejected(tmp_path):
    corpus = _make_corpus(tmp_path)
    path = tmp_path / "cases.jsonl"
    path.write_text("\n  \n\t\n", encoding="utf-8")
    with pytest.raises(ValueError, match="空|有效 Case"):
        RetrievalEvaluationSet.load_jsonl(path, corpus)


def test_blank_lines_ignored(tmp_path):
    corpus = _make_corpus(tmp_path)
    rows = _rows()
    path = tmp_path / "cases.jsonl"
    text = "\n\n" + json.dumps(rows[0], ensure_ascii=False) + "\n  \n" + json.dumps(rows[1], ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    evalset = RetrievalEvaluationSet.load_jsonl(path, corpus)
    assert [c.case_id for c in evalset.cases] == ["q001", "q002"]
