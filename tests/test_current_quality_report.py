"""Recorded outcomes and usage must remain distinct and fail on invalid data."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.report_current_quality import (
    ARCHIVE, REPO_ROOT, build_report, current_identity, render_markdown,
    request_usage, summarize_phase, verified_json,
)


@pytest.fixture(scope="module")
def report():
    return build_report()


@pytest.fixture
def recorded_case():
    base = REPO_ROOT / ARCHIVE / "acquisition"
    row = json.loads((base / "raw/development/live_results.jsonl").read_text(encoding="utf-8").splitlines()[0])
    review = json.loads((base / "manual_review.json").read_text(encoding="utf-8"))["phases"]["development"]["reviews"][0]
    return row, review


def test_recorded_totals_include_planner_and_repair_calls(report):
    assert report["experimental_usage_totals"] == {
        "requests": 54, "planner_calls": 54, "decision_calls": 241,
        "provider_calls": 295, "input_tokens": 1525739, "output_tokens": 31018,
    }
    assert len(report["phases"]) == 10
    assert report["independent_acceptance"] is False


def test_core_boundary_and_completed_are_not_conflated(report):
    phase = report["phases"]["acquisition/confirmation"]
    assert phase["core_scores"] == {"PASS": 4, "PARTIAL": 2, "FAIL": 0}
    assert phase["boundary_scores"] == {"PASS": 2, "PARTIAL": 0, "FAIL": 0}
    latest = report["latest_three_entries"]
    assert latest["scores"] == {"PASS": 1, "PARTIAL": 2, "FAIL": 0}
    assert all(case["status"] == "completed" for case in latest["cases"])
    assert report["phases"]["acquisition/entry_confirmation"]["core_scores"]["FAIL"] == 1
    assert "54 个请求 / 295" in render_markdown(report)


def test_current_code_hash_difference_is_not_historical_corruption(tmp_path):
    source = tmp_path / "api/app.py"
    source.parent.mkdir()
    source.write_text("changed\n", encoding="utf-8")
    recorded = {"api/app.py": "0" * 64, "core/missing.py": "1" * 64}
    state = current_identity(tmp_path, recorded)
    assert state["matches_last_live_product_files"] is False
    assert state["changed_since_last_live"] == ["api/app.py"]
    assert state["missing_since_last_live"] == ["core/missing.py"]
    state = current_identity(tmp_path, {"api/app.py": hashlib.sha256(source.read_bytes()).hexdigest()})
    assert state["matches_last_live_product_files"] is True


def test_archived_bytes_changed_are_rejected(tmp_path):
    source = tmp_path / "review.json"
    source.write_text('{"score":"FAIL"}', encoding="utf-8")
    frozen = hashlib.sha256(source.read_bytes()).hexdigest()
    source.write_text('{"score":"PASS"}', encoding="utf-8")
    with pytest.raises(ValueError, match="SHA mismatch"):
        verified_json(source, frozen)


@pytest.mark.parametrize("invalid", [None, True, -1])
def test_missing_or_invalid_tokens_are_not_reported_as_zero(recorded_case, invalid):
    row, _ = deepcopy(recorded_case)
    event = next(item for item in row["observations"] if item["stage"] == "planner")
    event["call_metadata"]["input_tokens"] = invalid
    with pytest.raises(ValueError, match="usage missing/invalid"):
        request_usage(row)


def test_duplicate_reviews_and_budget_overrun_are_rejected(recorded_case):
    row, review = recorded_case
    with pytest.raises(ValueError, match="Duplicate case ID"):
        summarize_phase([row], [review, review])
    row = deepcopy(row)
    row["public_response"]["tool_calls_used"] = 5
    with pytest.raises(ValueError, match="budget violation"):
        summarize_phase([row], [review])
