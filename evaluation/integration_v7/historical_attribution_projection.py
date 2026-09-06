"""Project persisted historical artifacts into separated attribution domains.

This evaluation-only module intentionally reports the limits of a historical
safe artifact.  It derives Gold structural evidence only from its persisted
``activity.evidence_added`` public fields.  It never reconstructs a Runtime
requirement state or a Router decision from the current product.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import finalization_attribution as _finalization_attribution
from .case_contract import DEV_SPLIT, ProtocolViolation, load_cases


HISTORICAL_ATTRIBUTION_PROJECTION_VERSION = (
    "integration_v7_historical_attribution_projection_v1"
)
AVAILABLE = "AVAILABLE"
HISTORICAL_ARTIFACT_FIELD_NOT_PRESERVED = "HISTORICAL_ARTIFACT_FIELD_NOT_PRESERVED"
NOT_APPLICABLE_INVALID_RUN = "NOT_APPLICABLE_INVALID_RUN"
_VALID_RUN = "VALID"
_INVALID_RUN = "INVALID"
_COMPLETED_STATUS = "completed"


class HistoricalAttributionProjectionError(ValueError):
    """Raised when an offline historical attribution input is malformed."""


@dataclass(frozen=True)
class HistoricalFinalizationAttributionProjection:
    """Only the attribution facts recoverable from a persisted safe artifact."""

    case_id: str
    run_validity: str
    final_status: str | None
    gold_evidence_groups_satisfied: bool | None
    gold_min_project_code_paths_satisfied: bool | None
    gold_structural_evidence_satisfied: bool | None
    gold_incomplete_at_completion: bool | None
    runtime_premature_finalization: None
    router_gold_contract_match: None
    attribution_availability: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        """Return the bounded, serializable projection record."""

        return {
            "schema_version": HISTORICAL_ATTRIBUTION_PROJECTION_VERSION,
            "case_id": self.case_id,
            "run_validity": self.run_validity,
            "final_status": self.final_status,
            "gold_evidence_groups_satisfied": self.gold_evidence_groups_satisfied,
            "gold_min_project_code_paths_satisfied": (
                self.gold_min_project_code_paths_satisfied
            ),
            "gold_structural_evidence_satisfied": self.gold_structural_evidence_satisfied,
            "gold_incomplete_at_completion": self.gold_incomplete_at_completion,
            "runtime_premature_finalization": self.runtime_premature_finalization,
            "router_gold_contract_match": self.router_gold_contract_match,
            "attribution_availability": dict(self.attribution_availability),
        }


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HistoricalAttributionProjectionError(f"{label} must be an object")
    return value


def _case_id(value: Mapping[str, Any], label: str) -> str:
    case_id = value.get("case_id")
    if type(case_id) is not str or not case_id:
        raise HistoricalAttributionProjectionError(f"{label}.case_id must be a non-empty string")
    return case_id


def _final_status(raw_run: Mapping[str, Any]) -> str | None:
    final = raw_run.get("final")
    if not isinstance(final, Mapping):
        return None
    status = final.get("status")
    if status in {_COMPLETED_STATUS, "refused"}:
        return status
    return None


def _persisted_public_evidence(raw_run: Mapping[str, Any]) -> list[dict[str, object]]:
    """Read only public evidence fields retained in safe Activity events."""

    activity = raw_run.get("activity")
    if isinstance(activity, (str, bytes, Mapping)) or not isinstance(activity, Sequence):
        raise HistoricalAttributionProjectionError("VALID raw run activity must be a sequence")

    evidence: list[dict[str, object]] = []
    for event in activity:
        if not isinstance(event, Mapping) or event.get("type") != "evidence_added":
            continue
        evidence.append({"kind": event.get("kind"), "path": event.get("path")})
    return evidence


def _gold_structural_state(
    frozen_case: Mapping[str, Any], public_evidence: Sequence[Mapping[str, object]]
) -> tuple[bool, bool, bool]:
    """Use the frozen 14B Gold group and public-path semantics verbatim.

    This deliberately calls the accepted 14B structural helpers rather than
    fabricating the absent historical Runtime requirement state required by
    ``attribute_finalization``.
    """

    groups = _finalization_attribution._canonical_groups(
        frozen_case.get("required_evidence_groups"),
        "frozen case required_evidence_groups",
    )
    minimum = _finalization_attribution._strict_non_negative_int(
        frozen_case.get("min_distinct_project_code_paths"),
        "frozen case min_distinct_project_code_paths",
    )
    evidence_kinds = {
        _finalization_attribution._evidence_kind(item)
        for item in public_evidence
        if type(_finalization_attribution._evidence_kind(item)) is str
    }
    groups_satisfied = all(
        any(kind in evidence_kinds for kind in group) for group in groups
    )
    code_paths = {
        path
        for item in public_evidence
        if _finalization_attribution._evidence_kind(item) == "project_code"
        for path in (_finalization_attribution._evidence_path(item),)
        if _finalization_attribution._is_repo_relative_public_path(path)
    }
    minimum_satisfied = len(code_paths) >= minimum
    return groups_satisfied, minimum_satisfied, groups_satisfied and minimum_satisfied


def _project_one(
    frozen_case: Mapping[str, Any], raw_run: Mapping[str, Any]
) -> HistoricalFinalizationAttributionProjection:
    case_id = _case_id(raw_run, "raw run")
    if case_id != _case_id(frozen_case, "frozen case"):
        raise HistoricalAttributionProjectionError("raw run and frozen case IDs disagree")
    validity = raw_run.get("run_validity")
    if validity not in {_VALID_RUN, _INVALID_RUN}:
        raise HistoricalAttributionProjectionError(
            f"raw run {case_id} has unsupported run_validity {validity!r}"
        )

    final_status = _final_status(raw_run)
    if validity == _INVALID_RUN:
        unavailable = {
            "gold_structural": NOT_APPLICABLE_INVALID_RUN,
            "runtime_premature_finalization": NOT_APPLICABLE_INVALID_RUN,
            "router_gold_contract_match": NOT_APPLICABLE_INVALID_RUN,
        }
        return HistoricalFinalizationAttributionProjection(
            case_id=case_id,
            run_validity=validity,
            final_status=final_status,
            gold_evidence_groups_satisfied=None,
            gold_min_project_code_paths_satisfied=None,
            gold_structural_evidence_satisfied=None,
            gold_incomplete_at_completion=None,
            runtime_premature_finalization=None,
            router_gold_contract_match=None,
            attribution_availability=unavailable,
        )

    groups_satisfied, minimum_satisfied, structural_satisfied = _gold_structural_state(
        frozen_case,
        _persisted_public_evidence(raw_run),
    )
    unavailable = {
        "gold_structural": AVAILABLE,
        "runtime_premature_finalization": HISTORICAL_ARTIFACT_FIELD_NOT_PRESERVED,
        "router_gold_contract_match": HISTORICAL_ARTIFACT_FIELD_NOT_PRESERVED,
    }
    return HistoricalFinalizationAttributionProjection(
        case_id=case_id,
        run_validity=validity,
        final_status=final_status,
        gold_evidence_groups_satisfied=groups_satisfied,
        gold_min_project_code_paths_satisfied=minimum_satisfied,
        gold_structural_evidence_satisfied=structural_satisfied,
        gold_incomplete_at_completion=(
            final_status == _COMPLETED_STATUS and not structural_satisfied
        ),
        runtime_premature_finalization=None,
        router_gold_contract_match=None,
        attribution_availability=unavailable,
    )


def project_historical_attribution(
    frozen_cases: Sequence[Mapping[str, Any]], raw_runs: Sequence[Mapping[str, Any]]
) -> list[HistoricalFinalizationAttributionProjection]:
    """Project persisted historical safe artifacts without product reconstruction."""

    if isinstance(frozen_cases, (str, bytes, Mapping)) or not isinstance(
        frozen_cases, Sequence
    ):
        raise HistoricalAttributionProjectionError("frozen_cases must be a sequence")
    if isinstance(raw_runs, (str, bytes, Mapping)) or not isinstance(raw_runs, Sequence):
        raise HistoricalAttributionProjectionError("raw_runs must be a sequence")

    cases_by_id: dict[str, Mapping[str, Any]] = {}
    for item in frozen_cases:
        case = _require_mapping(item, "frozen case")
        case_id = _case_id(case, "frozen case")
        if case_id in cases_by_id:
            raise HistoricalAttributionProjectionError(f"duplicate frozen case ID {case_id}")
        cases_by_id[case_id] = case

    records: list[HistoricalFinalizationAttributionProjection] = []
    seen_run_ids: set[str] = set()
    for item in raw_runs:
        raw_run = _require_mapping(item, "raw run")
        case_id = _case_id(raw_run, "raw run")
        if case_id in seen_run_ids:
            raise HistoricalAttributionProjectionError(f"duplicate raw run case ID {case_id}")
        if case_id not in cases_by_id:
            raise HistoricalAttributionProjectionError(
                f"raw run {case_id} does not exist in the supplied frozen cases"
            )
        seen_run_ids.add(case_id)
        records.append(_project_one(cases_by_id[case_id], raw_run))
    return records


def build_historical_projection_summary(
    records: Iterable[HistoricalFinalizationAttributionProjection],
) -> dict[str, Any]:
    """Summarize only facts that the projected records make available."""

    rows = list(records)
    valid_rows = [row for row in rows if row.run_validity == _VALID_RUN]
    invalid_rows = [row for row in rows if row.run_validity == _INVALID_RUN]
    incomplete_case_ids = sorted(
        row.case_id for row in valid_rows if row.gold_incomplete_at_completion is True
    )
    return {
        "schema_version": HISTORICAL_ATTRIBUTION_PROJECTION_VERSION,
        "observed_runs": len(rows),
        "valid_runs": len(valid_rows),
        "invalid_runs": len(invalid_rows),
        "valid_completed_runs": sum(
            row.final_status == _COMPLETED_STATUS for row in valid_rows
        ),
        "gold_incomplete_at_completion_count": len(incomplete_case_ids),
        "gold_incomplete_at_completion_case_ids": incomplete_case_ids,
        "runtime_premature_finalization_available": sum(
            row.runtime_premature_finalization is not None for row in rows
        ),
        "router_gold_contract_match_available": sum(
            row.router_gold_contract_match is not None for row in rows
        ),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise HistoricalAttributionProjectionError(f"input is missing: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise HistoricalAttributionProjectionError(
                    f"input {path} line {line_number} is blank"
                )
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise HistoricalAttributionProjectionError(
                    f"input {path} line {line_number} is invalid JSON"
                ) from exc
            if not isinstance(row, dict):
                raise HistoricalAttributionProjectionError(
                    f"input {path} line {line_number} must be an object"
                )
            rows.append(row)
    return rows


def _assert_outputs_absent(output: Path, summary_output: Path) -> None:
    if output == summary_output:
        raise HistoricalAttributionProjectionError("output and summary-output must differ")
    existing = [str(path) for path in (output, summary_output) if path.exists()]
    if existing:
        raise FileExistsError(
            "refusing to overwrite existing projection output(s): " + ", ".join(existing)
        )


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _load_explicit_dev_cases(path: Path) -> list[dict[str, Any]]:
    try:
        cases = load_cases(path)
    except ProtocolViolation as exc:
        raise HistoricalAttributionProjectionError(str(exc)) from exc
    if any(case.get("split") != DEV_SPLIT for case in cases):
        raise HistoricalAttributionProjectionError("projection accepts Integration Dev cases only")
    return cases


def main(argv: Sequence[str] | None = None) -> int:
    """Write a no-overwrite projection from explicitly supplied local inputs."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--raw-runs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary-output", required=True, type=Path)
    args = parser.parse_args(argv)

    _assert_outputs_absent(args.output, args.summary_output)
    records = project_historical_attribution(
        _load_explicit_dev_cases(args.cases), _read_jsonl(args.raw_runs)
    )
    serialized = [record.to_dict() for record in records]
    _write_jsonl(args.output, serialized)
    _write_json(args.summary_output, build_historical_projection_summary(records))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the module CLI.
    raise SystemExit(main())


__all__ = [
    "AVAILABLE",
    "HISTORICAL_ARTIFACT_FIELD_NOT_PRESERVED",
    "HISTORICAL_ATTRIBUTION_PROJECTION_VERSION",
    "HistoricalAttributionProjectionError",
    "HistoricalFinalizationAttributionProjection",
    "NOT_APPLICABLE_INVALID_RUN",
    "build_historical_projection_summary",
    "project_historical_attribution",
]
