"""Compare two completed G11-02 run directories without scoring answers."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


BASELINE_PROMPT_VERSION = "tool_agent_decision_prompt_v3"
BASELINE_PROMPT_SHA256 = "a6092bffdfee3236575ae0f801985e6c8d6aecedba339672bde838f1daed1dc1"
POST_PROMPT_VERSION = "engineering_agent_decision_prompt_v1"
POST_PROMPT_SHA256 = "aa99e543d2bfbd3315113842e5377bf52bff7dcf50fc843840785ddee34dfa0a"
REQUIRED_TOOLS = ("knowledge_search", "code_search", "read_project_context")
FORBIDDEN_TOOLS = ("changed_files", "git_diff", "find_tests", "calculator")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ComparisonValidationError(ValueError):
    """The two runs are not a valid controlled comparison pair."""


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComparisonValidationError(f"invalid JSON artifact: {path.name}") from exc
    if not isinstance(value, dict):
        raise ComparisonValidationError(f"artifact must contain an object: {path.name}")
    return value


def _read_cases(run_dir: Path) -> list[dict]:
    path = run_dir / "case_results.jsonl"
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    except (OSError, json.JSONDecodeError) as exc:
        raise ComparisonValidationError("invalid case_results.jsonl") from exc
    if not all(isinstance(row, dict) for row in rows):
        raise ComparisonValidationError("case_results.jsonl must contain objects")
    ids = [row.get("case_id") for row in rows]
    if any(not isinstance(case_id, str) for case_id in ids) or len(set(ids)) != len(ids):
        raise ComparisonValidationError("case results must have unique case_id values")
    return rows


def _validate_manifest(manifest: dict, label: str) -> None:
    required = (
        "run_id",
        "source_commit",
        "project_identity",
        "knowledge_corpus_id",
        "provider",
        "model",
        "prompt_version",
        "prompt_sha256",
        "toolset_sha256",
        "budget",
        "case_ids",
    )
    missing = [key for key in required if key not in manifest]
    if missing:
        raise ComparisonValidationError(f"{label} manifest missing: {', '.join(missing)}")
    if not isinstance(manifest["source_commit"], str) or not _COMMIT_RE.fullmatch(
        manifest["source_commit"]
    ):
        raise ComparisonValidationError(f"{label} source_commit is not normalized 40-char SHA")
    if not isinstance(manifest["prompt_sha256"], str) or not _SHA256_RE.fullmatch(
        manifest["prompt_sha256"]
    ):
        raise ComparisonValidationError(f"{label} prompt_sha256 is not normalized 64-char SHA")
    if not isinstance(manifest["case_ids"], list) or not manifest["case_ids"]:
        raise ComparisonValidationError(f"{label} case_ids must be a non-empty list")
    if not isinstance(manifest["budget"], dict):
        raise ComparisonValidationError(f"{label} budget must be an object")


def _validate_run_pair(
    baseline_manifest: dict,
    post_manifest: dict,
    baseline_cases: list[dict],
    post_cases: list[dict],
) -> None:
    _validate_manifest(baseline_manifest, "baseline")
    _validate_manifest(post_manifest, "post")
    for key in (
        "project_identity",
        "knowledge_corpus_id",
        "provider",
        "model",
        "toolset_sha256",
        "budget",
        "case_ids",
    ):
        if baseline_manifest[key] != post_manifest[key]:
            raise ComparisonValidationError(f"non-comparable {key}")
    if (
        baseline_manifest["prompt_version"] != BASELINE_PROMPT_VERSION
        or baseline_manifest["prompt_sha256"] != BASELINE_PROMPT_SHA256
    ):
        raise ComparisonValidationError("baseline prompt identity is not v3")
    if (
        post_manifest["prompt_version"] != POST_PROMPT_VERSION
        or post_manifest["prompt_sha256"] != POST_PROMPT_SHA256
    ):
        raise ComparisonValidationError("post prompt identity is not engineering v1")
    if baseline_manifest["prompt_version"] == post_manifest["prompt_version"]:
        raise ComparisonValidationError("baseline and post prompt profiles must differ")
    expected_ids = baseline_manifest["case_ids"]
    if [row["case_id"] for row in baseline_cases] != expected_ids:
        raise ComparisonValidationError("baseline case order does not match manifest")
    if [row["case_id"] for row in post_cases] != expected_ids:
        raise ComparisonValidationError("post case order does not match manifest")


def _metrics(cases: list[dict]) -> dict:
    count = len(cases)
    completed = sum(row.get("status") == "completed" for row in cases)
    cross_source = sum(
        {"knowledge", "project_code"}.issubset(set(row.get("evidence_kinds", [])))
        for row in cases
    )
    required = {
        tool: sum(tool in row.get("tool_sequence", []) for row in cases)
        for tool in REQUIRED_TOOLS
    }
    forbidden = sum(
        any(tool in FORBIDDEN_TOOLS for tool in row.get("tool_sequence", []))
        for row in cases
    )
    return {
        "case_count": count,
        "completed_cases": completed,
        "completion_rate": completed / count if count else 0,
        "cross_source_cases": cross_source,
        "cross_source_evidence_rate": cross_source / count if count else 0,
        "required_tool_coverage": required,
        "required_tool_coverage_rate": (
            sum(required.values()) / (len(REQUIRED_TOOLS) * count) if count else 0
        ),
        "forbidden_tool_calls": forbidden,
        "forbidden_tool_call_rate": forbidden / count if count else 0,
        "avg_tool_calls": sum(row.get("tool_calls_used") or 0 for row in cases) / count if count else 0,
        "avg_iterations": sum(row.get("iterations_used") or 0 for row in cases) / count if count else 0,
        "evidence_count": sum(len(row.get("evidence", [])) for row in cases),
        "refused_cases": sum(row.get("status") == "refused" for row in cases),
        "failed_cases": sum(row.get("status") == "failed" for row in cases),
    }


def _metric_display(metrics: dict, key: str) -> str:
    if key == "completed_cases":
        return f"{metrics[key]}/{metrics['case_count']}"
    if key == "cross_source_evidence_rate":
        return f"{metrics['cross_source_cases']}/{metrics['case_count']} ({metrics[key]:.3f})"
    if key == "required_tool_coverage":
        return json.dumps(metrics[key], ensure_ascii=False, sort_keys=True)
    return str(metrics[key])


def compare_runs(baseline_dir: str | Path, post_dir: str | Path, output_dir: str | Path) -> Path:
    baseline_dir = Path(baseline_dir)
    post_dir = Path(post_dir)
    output_dir = Path(output_dir)
    baseline_manifest = _read_json(baseline_dir / "manifest.json")
    post_manifest = _read_json(post_dir / "manifest.json")
    baseline_cases = _read_cases(baseline_dir)
    post_cases = _read_cases(post_dir)
    _validate_run_pair(baseline_manifest, post_manifest, baseline_cases, post_cases)
    output_dir.mkdir(parents=True, exist_ok=False)

    baseline_metrics = _metrics(baseline_cases)
    post_metrics = _metrics(post_cases)
    comparison_manifest = {
        "schema_version": "g11_02_comparison_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline_run_id": baseline_manifest["run_id"],
        "post_run_id": post_manifest["run_id"],
        "baseline_source_commit": baseline_manifest["source_commit"],
        "post_source_commit": post_manifest["source_commit"],
        "baseline_prompt_version": baseline_manifest["prompt_version"],
        "baseline_prompt_sha256": baseline_manifest["prompt_sha256"],
        "post_prompt_version": post_manifest["prompt_version"],
        "post_prompt_sha256": post_manifest["prompt_sha256"],
        "project_identity": baseline_manifest["project_identity"],
        "knowledge_corpus_id": baseline_manifest["knowledge_corpus_id"],
        "provider": baseline_manifest["provider"],
        "model": baseline_manifest["model"],
        "toolset_sha256": baseline_manifest["toolset_sha256"],
        "budget": baseline_manifest["budget"],
        "case_ids": baseline_manifest["case_ids"],
        "correctness_scored": False,
        "gold_obligations_manual_only": True,
    }
    (output_dir / "comparison_manifest.json").write_text(
        json.dumps(comparison_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    metric_keys = (
        "completed_cases",
        "cross_source_evidence_rate",
        "required_tool_coverage",
        "forbidden_tool_call_rate",
        "avg_tool_calls",
        "avg_iterations",
        "evidence_count",
        "refused_cases",
        "failed_cases",
    )
    lines = [
        "# G11-02 Theory <-> Code A/B Comparison",
        "",
        "Structural comparison only. Correctness was not automatically scored; Gold obligations remain for manual audit.",
        "",
        "## Run Identity",
        "",
        f"- baseline_run_id: `{baseline_manifest['run_id']}`",
        f"- post_run_id: `{post_manifest['run_id']}`",
        f"- baseline_source_commit: `{baseline_manifest['source_commit']}`",
        f"- post_source_commit: `{post_manifest['source_commit']}`",
        f"- baseline_prompt: `{baseline_manifest['prompt_version']}` / `{baseline_manifest['prompt_sha256']}`",
        f"- post_prompt: `{post_manifest['prompt_version']}` / `{post_manifest['prompt_sha256']}`",
        f"- project_identity: `{baseline_manifest['project_identity']}`",
        f"- knowledge_corpus_id: `{baseline_manifest['knowledge_corpus_id']}`",
        f"- provider/model: `{baseline_manifest['provider']}` / `{baseline_manifest['model']}`",
        f"- toolset_sha256: `{baseline_manifest['toolset_sha256']}`",
        f"- budget: `{json.dumps(baseline_manifest['budget'], sort_keys=True)}`",
        "",
        "## Structural Metrics",
        "",
        "| Metric | Baseline | Post-change |",
        "|---|---:|---:|",
    ]
    for key in metric_keys:
        lines.append(
            f"| {key} | {_metric_display(baseline_metrics, key)} | {_metric_display(post_metrics, key)} |"
        )
    lines.extend(["", "## Per-case Comparison", ""])
    for baseline_case, post_case in zip(baseline_cases, post_cases):
        lines.extend(
            [
                f"### {baseline_case['case_id']}",
                "",
                f"- baseline status: `{baseline_case.get('status')}`",
                f"- post status: `{post_case.get('status')}`",
                f"- baseline tool sequence: `{' -> '.join(baseline_case.get('tool_sequence', [])) or '(none)'}`",
                f"- post tool sequence: `{' -> '.join(post_case.get('tool_sequence', [])) or '(none)'}`",
                f"- baseline evidence kinds: `{', '.join(baseline_case.get('evidence_kinds', [])) or '(none)'}`",
                f"- post evidence kinds: `{', '.join(post_case.get('evidence_kinds', [])) or '(none)'}`",
                "",
            ]
        )
    (output_dir / "comparison_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--post", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = compare_runs(args.baseline, args.post, args.output)
    print(json.dumps({"output": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    main()
