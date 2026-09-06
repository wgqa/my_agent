"""Provider-free tests for ARCH-EVAL-14C-MICRO."""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.integration_v7.historical_attribution_projection import (
    AVAILABLE,
    HISTORICAL_ARTIFACT_FIELD_NOT_PRESERVED,
    HISTORICAL_ATTRIBUTION_PROJECTION_VERSION,
    NOT_APPLICABLE_INVALID_RUN,
    HistoricalAttributionProjectionError,
    _assert_outputs_absent,
    build_historical_projection_summary,
    project_historical_attribution,
)


def _case(case_id="v7d001", groups=(("project_code",),), minimum=0):
    return {
        "case_id": case_id,
        "required_evidence_groups": [list(group) for group in groups],
        "min_distinct_project_code_paths": minimum,
    }


def _run(case_id="v7d001", *, validity="VALID", status="completed", activity=()):
    return {
        "case_id": case_id,
        "run_validity": validity,
        "final": {"status": status},
        "activity": list(activity),
        # This persisted field must never be interpreted as Runtime state.
        "missing_evidence_groups": [],
    }


def _evidence(kind, path=None):
    event = {"type": "evidence_added", "kind": kind}
    if path is not None:
        event["path"] = path
    return event


def _one(case, run):
    return project_historical_attribution([case], [run])[0]


def test_gold_groups_use_and_of_or_semantics_from_persisted_evidence_added_events():
    record = _one(
        _case(groups=(("knowledge",), ("project_code", "project_doc"))),
        _run(activity=(_evidence("knowledge"), _evidence("project_code", "src/app.py"))),
    )
    assert record.gold_evidence_groups_satisfied is True
    assert record.gold_structural_evidence_satisfied is True
    assert record.attribution_availability["gold_structural"] == AVAILABLE


def test_completed_run_with_incomplete_gold_is_not_recast_as_runtime_premature():
    record = _one(
        _case(groups=(("project_code",),)),
        _run(activity=(_evidence("knowledge"),)),
    )
    assert record.gold_structural_evidence_satisfied is False
    assert record.gold_incomplete_at_completion is True
    assert record.runtime_premature_finalization is None
    assert record.attribution_availability["runtime_premature_finalization"] == (
        HISTORICAL_ARTIFACT_FIELD_NOT_PRESERVED
    )


def test_refusal_with_incomplete_gold_is_not_incomplete_at_completion():
    record = _one(
        _case(groups=(("project_code",),)),
        _run(status="refused", activity=(_evidence("knowledge"),)),
    )
    assert record.gold_structural_evidence_satisfied is False
    assert record.gold_incomplete_at_completion is False


def test_distinct_code_path_floor_counts_only_distinct_public_project_code_paths():
    record = _one(
        _case(minimum=2),
        _run(
            activity=(
                _evidence("project_code", "src/a.py"),
                _evidence("project_code", "src/a.py"),
                _evidence("project_code", "src/b.py"),
                _evidence("project_doc", "docs/a.md"),
                _evidence("project_test", "tests/test_a.py"),
            )
        ),
    )
    assert record.gold_min_project_code_paths_satisfied is True


def test_project_code_path_floor_rejects_duplicates_and_non_code_evidence():
    record = _one(
        _case(minimum=2),
        _run(
            activity=(
                _evidence("project_code", "src/a.py"),
                _evidence("project_code", "src/a.py"),
                _evidence("project_doc", "src/b.py"),
                _evidence("project_test", "tests/test_a.py"),
                _evidence("project_change", "src/c.py"),
            )
        ),
    )
    assert record.gold_min_project_code_paths_satisfied is False


def test_invalid_run_has_only_null_attribution_and_not_applicable_availability():
    record = _one(_case(), _run(validity="INVALID", status="completed"))
    assert record.gold_evidence_groups_satisfied is None
    assert record.gold_min_project_code_paths_satisfied is None
    assert record.gold_structural_evidence_satisfied is None
    assert record.gold_incomplete_at_completion is None
    assert record.runtime_premature_finalization is None
    assert record.router_gold_contract_match is None
    assert set(record.attribution_availability.values()) == {NOT_APPLICABLE_INVALID_RUN}


def test_historical_runtime_attribution_stays_unavailable_despite_empty_missing_groups():
    record = _one(_case(), _run(activity=(_evidence("project_code", "src/a.py"),)))
    assert record.runtime_premature_finalization is None
    assert record.attribution_availability["runtime_premature_finalization"] == (
        HISTORICAL_ARTIFACT_FIELD_NOT_PRESERVED
    )


def test_router_gold_contract_stays_unavailable_without_current_router_reconstruction():
    record = _one(_case(), _run(activity=(_evidence("project_code", "src/a.py"),)))
    assert record.router_gold_contract_match is None
    assert record.attribution_availability["router_gold_contract_match"] == (
        HISTORICAL_ARTIFACT_FIELD_NOT_PRESERVED
    )


def test_summary_reports_only_available_historical_domains_without_hardcoded_case_ids():
    records = project_historical_attribution(
        [_case("v7d001"), _case("v7d002"), _case("v7d003")],
        [
            _run("v7d001", activity=(_evidence("project_code", "src/a.py"),)),
            _run("v7d002", activity=(_evidence("knowledge"),)),
            _run("v7d003", validity="INVALID"),
        ],
    )
    summary = build_historical_projection_summary(records)
    assert summary == {
        "schema_version": HISTORICAL_ATTRIBUTION_PROJECTION_VERSION,
        "observed_runs": 3,
        "valid_runs": 2,
        "invalid_runs": 1,
        "valid_completed_runs": 2,
        "gold_incomplete_at_completion_count": 1,
        "gold_incomplete_at_completion_case_ids": ["v7d002"],
        "runtime_premature_finalization_available": 0,
        "router_gold_contract_match_available": 0,
    }


def test_projection_rejects_unknown_or_duplicate_raw_case_ids():
    with pytest.raises(HistoricalAttributionProjectionError, match="does not exist"):
        project_historical_attribution([_case()], [_run("v7d099")])
    with pytest.raises(HistoricalAttributionProjectionError, match="duplicate raw run"):
        project_historical_attribution([_case()], [_run(), _run()])


def test_cli_output_preflight_refuses_to_overwrite_existing_paths(tmp_path: Path):
    output = tmp_path / "projection.jsonl"
    summary = tmp_path / "summary.json"
    output.write_text("existing\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        _assert_outputs_absent(output, summary)
    with pytest.raises(HistoricalAttributionProjectionError, match="must differ"):
        _assert_outputs_absent(summary, summary)
