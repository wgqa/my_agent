"""Run the bounded, live Release 1.0 demo over the public HTTP API.

This is a product demonstration harness, not a benchmark.  It performs one
request per catalog case, never retries a model call, and stores only safe
summaries when an output artifact is requested.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = REPO_ROOT / "demo" / "release_demo_cases.json"
FIXTURES = (
    REPO_ROOT / "demo" / "fixtures" / "retrieval_basics.md",
    REPO_ROOT / "demo" / "fixtures" / "agent_architecture.md",
)
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "runtime" / "release_demo_run.json"
MAX_CASES = 6
REQUEST_TIMEOUT_SECONDS = 30.0
ALLOWED_AGENT_STATUSES = frozenset({"completed", "refused", "deferred", "failed"})
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(api[_ -]?key|authorization|system[_ -]?prompt|raw[_ -]?output|traceback)"
    r"\s*[:=]\s*[^\s,;]+"
)
_SECRET_TOKEN = re.compile(r"(?i)\bsk-[A-Za-z0-9_-]+\b")
_WINDOWS_PATH = re.compile(r"(?i)\b[A-Za-z]:\\[^\s]+")
_POSIX_PATH = re.compile(r"(?<![\w:])/(?:[^\s/]+/)+[^\s]+")


class DemoApiError(RuntimeError):
    """Bounded API failure used by the demo output and tests."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class DemoHttpClient:
    """Minimal HTTP transport for the formal API endpoints."""

    def __init__(self, base_url: str, timeout: float = REQUEST_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs) -> tuple[int, dict]:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout,
                **kwargs,
            )
        except requests.exceptions.Timeout as exc:
            raise DemoApiError("request timed out") from exc
        except requests.exceptions.RequestException as exc:
            raise DemoApiError(f"request failed: {type(exc).__name__}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise DemoApiError(
                "API returned invalid JSON", status_code=response.status_code
            ) from exc
        if not isinstance(payload, dict):
            raise DemoApiError(
                "API returned an invalid object", status_code=response.status_code
            )
        if response.status_code >= 400:
            raise DemoApiError(
                f"HTTP {response.status_code}", status_code=response.status_code
            )
        return response.status_code, payload

    def get(self, path: str) -> tuple[int, dict]:
        return self._request("GET", path)

    def post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        return self._request("POST", path, json=payload)

    def upload_file(self, path: Path) -> tuple[int, dict]:
        try:
            with path.open("rb") as handle:
                return self._request(
                    "POST",
                    "/index/file",
                    files={"file": (path.name, handle, "text/markdown")},
                )
        except OSError as exc:
            raise DemoApiError(f"fixture read failed: {path.name}") from exc


@dataclass(frozen=True)
class Preflight:
    health_ok: bool = False
    capabilities_ok: bool = False
    pipeline_ready: bool = False
    basic_rag_ready: bool = False
    agentic_rag_ready: bool = False
    tool_agent_ready: bool = False
    health_error: str | None = None
    capabilities_error: str | None = None


@dataclass
class CaseResult:
    case_id: str
    endpoint: str
    required: bool
    observational: bool
    status: str
    http_status: int | None = None
    safe_summary: str = ""
    tool_names: list[str] = field(default_factory=list)
    actual_tool_sequence: list[str] = field(default_factory=list)
    tool_calls: int = 0
    evidence_count: int = 0
    query_type: str | None = None
    route: str | None = None
    answer_excerpt: str = ""
    error: str | None = None


def safe_text(value: Any, limit: int = 240) -> str:
    """Bound and redact text before it reaches terminal output or artifacts."""
    text = str(value or "")
    text = _SENSITIVE_ASSIGNMENT.sub("[REDACTED]", text)
    text = _SECRET_TOKEN.sub("[REDACTED]", text)
    text = _WINDOWS_PATH.sub("[PATH]", text)
    text = _POSIX_PATH.sub("[PATH]", text)
    return text[:limit]


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        cases = json.load(handle)
    if not isinstance(cases, list) or len(cases) != MAX_CASES:
        raise ValueError(f"demo case catalog must contain exactly {MAX_CASES} cases")
    ids = [case.get("id") for case in cases]
    if any(not isinstance(case, dict) for case in cases) or len(set(ids)) != len(ids):
        raise ValueError("demo case ids must be unique")
    if sum(bool(case.get("observational")) for case in cases) != 1:
        raise ValueError("catalog must contain exactly one observational case")
    if sum(bool(case.get("required", True)) for case in cases) != 5:
        raise ValueError("catalog must contain exactly five required cases")
    return cases


def build_payload(case: dict) -> dict:
    mode = case.get("mode")
    question = case.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"case {case.get('id')!r} has no question")
    if mode in {"basic_rag", "agentic_rag"}:
        return {"question": question, "top_k": 5}
    if mode == "tool_agent":
        return {"question": question}
    raise ValueError(f"unsupported demo mode: {mode!r}")


def preflight(client: DemoHttpClient) -> Preflight:
    health_ok = False
    capabilities_ok = False
    health_error = None
    capabilities_error = None

    try:
        health_status, _ = client.get("/health")
        health_ok = health_status == 200
        if not health_ok:
            health_error = f"HTTP {health_status}"
    except DemoApiError as exc:
        health_error = safe_text(exc)

    try:
        capabilities_status, payload = client.get("/capabilities")
        capabilities_ok = capabilities_status == 200
        if not capabilities_ok:
            capabilities_error = f"HTTP {capabilities_status}"
        features = payload.get("features")
        if not isinstance(features, dict):
            features = {}
        return Preflight(
            health_ok=health_ok,
            capabilities_ok=capabilities_ok,
            pipeline_ready=bool(payload.get("pipeline_ready")),
            basic_rag_ready=bool(features.get("basic_rag")),
            agentic_rag_ready=bool(payload.get("agent_runtime_ready"))
            and bool(features.get("agentic_rag")),
            tool_agent_ready=bool(payload.get("tool_agent_runtime_ready"))
            and bool(features.get("structured_tool_agent")),
            health_error=health_error,
            capabilities_error=capabilities_error,
        )
    except DemoApiError as exc:
        capabilities_error = safe_text(exc)
        return Preflight(
            health_ok=health_ok,
            capabilities_ok=False,
            health_error=health_error,
            capabilities_error=capabilities_error,
        )


def _ready_for_case(case: dict, status: Preflight) -> bool:
    if not status.health_ok or not status.capabilities_ok:
        return False
    mode = case.get("mode")
    if mode == "basic_rag":
        return status.basic_rag_ready
    if mode == "agentic_rag":
        return status.agentic_rag_ready
    if mode == "tool_agent":
        return status.tool_agent_ready
    return False


def _tool_sequence(response: dict) -> list[str]:
    trace = response.get("trace")
    if not isinstance(trace, list):
        return []
    return [
        str(event["tool_name"])
        for event in trace
        if isinstance(event, dict) and event.get("tool_name")
    ]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _validate_response(case: dict, response: dict, http_status: int) -> tuple[list[str], CaseResult]:
    result = CaseResult(
        case_id=case["id"],
        endpoint=case["endpoint"],
        required=bool(case.get("required", True)),
        observational=bool(case.get("observational", False)),
        status="failed",
        http_status=http_status,
    )
    errors: list[str] = []
    expected = case.get("expected", {})
    if http_status != expected.get("http_status", 200):
        errors.append(f"HTTP {http_status}")

    answer = response.get("answer")
    if isinstance(answer, str):
        result.answer_excerpt = safe_text(answer)
    if case["mode"] == "basic_rag":
        sources = response.get("sources")
        result.evidence_count = len(sources) if isinstance(sources, list) else 0
        if expected.get("answer_non_empty") and not str(answer or "").strip():
            errors.append("empty answer")
        if result.evidence_count < int(expected.get("sources_min", 0)):
            errors.append("insufficient sources")
        result.safe_summary = f"sources={result.evidence_count}"
    elif case["mode"] == "agentic_rag":
        status = response.get("status")
        result.query_type = (response.get("planner") or {}).get("plan", {}).get(
            "query_type"
        )
        result.route = (response.get("route") or {}).get("route")
        sources = response.get("sources")
        result.evidence_count = len(sources) if isinstance(sources, list) else 0
        if response.get("schema_version") != "agent_query_response_v1":
            errors.append("invalid agent response schema")
        if status not in ALLOWED_AGENT_STATUSES:
            errors.append("invalid agent status")
        if not isinstance(response.get("run_id"), str) or not isinstance(
            response.get("trace"), list
        ):
            errors.append("incomplete agent response")
        if status == "completed":
            if not str(answer or "").strip():
                errors.append("completed agent answer is empty")
            if not response.get("planner") or not response.get("route"):
                errors.append("completed agent response lacks planner/route")
        result.safe_summary = (
            f"status={safe_text(status)} query_type={safe_text(result.query_type)} "
            f"route={safe_text(result.route)} evidence={result.evidence_count}"
        )
    else:
        result.actual_tool_sequence = _tool_sequence(response)
        result.tool_names = _unique(result.actual_tool_sequence)
        result.tool_calls = int(response.get("tool_calls_used") or 0)
        if response.get("schema_version") != "tool_agent_query_response_v1":
            errors.append("invalid tool-agent response schema")
        if expected.get("tool_calls_min", 0) > result.tool_calls:
            errors.append("insufficient tool calls")
        wanted_tool = expected.get("tool_name")
        if wanted_tool and wanted_tool not in result.tool_names:
            errors.append(f"missing tool {wanted_tool}")
        forbidden_tool = expected.get("forbid_tool_name")
        if forbidden_tool and forbidden_tool in result.tool_names:
            errors.append(f"forbidden tool executed: {forbidden_tool}")
        if expected.get("answer_contains") and expected["answer_contains"] not in str(answer or ""):
            errors.append("expected calculator result missing")
        result.safe_summary = (
            f"tools={','.join(result.tool_names) or 'none'} "
            f"tool_calls={result.tool_calls} shell_executed="
            f"{'shell' in result.tool_names}"
        )

    result.status = "pass" if not errors else "fail"
    result.error = "; ".join(errors) if errors else None
    return errors, result


def run_case(client: DemoHttpClient, case: dict, status: Preflight) -> CaseResult:
    """Run one catalog case exactly once, or skip it before making a request."""
    base = CaseResult(
        case_id=case["id"],
        endpoint=case["endpoint"],
        required=bool(case.get("required", True)),
        observational=bool(case.get("observational", False)),
        status="skipped",
    )
    if not _ready_for_case(case, status):
        base.safe_summary = "NOT READY"
        base.error = "runtime unavailable; request skipped"
        return base

    try:
        http_status, response = client.post_json(case["endpoint"], build_payload(case))
    except (DemoApiError, ValueError) as exc:
        base.status = "fail"
        base.safe_summary = "API request failed"
        base.error = safe_text(exc)
        return base
    _errors, result = _validate_response(case, response, http_status)
    return result


def upload_fixtures(client: DemoHttpClient) -> list[str]:
    uploaded: list[str] = []
    for fixture in FIXTURES:
        status, _ = client.upload_file(fixture)
        if status != 200:
            raise DemoApiError(f"fixture upload failed: {fixture.name}", status_code=status)
        uploaded.append(fixture.name)
    return uploaded


def build_artifact(results: list[CaseResult], source_commit: str, timestamp: str) -> dict:
    return {
        "timestamp": timestamp,
        "source_commit": safe_text(source_commit, limit=80),
        "cases": [
            {
                "case_id": result.case_id,
                "endpoint": result.endpoint,
                "status": result.status,
                "required": result.required,
                "observational": result.observational,
                "safe_summary": safe_text(result.safe_summary),
                "tool_names": list(result.tool_names),
                "counts": {
                    "tool_calls": result.tool_calls,
                    "evidence": result.evidence_count,
                },
            }
            for result in results
        ],
    }


def write_artifact(path: Path, artifact: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def display_artifact_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return path.name


def source_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _print_preflight(status: Preflight) -> None:
    print("[Preflight]")
    print(f"Pipeline: {'READY' if status.pipeline_ready else 'NOT READY'}")
    print(f"Basic RAG: {'READY' if status.basic_rag_ready else 'NOT READY'}")
    print(f"Agentic RAG: {'READY' if status.agentic_rag_ready else 'NOT READY'}")
    print(
        "Structured Tool Agent: "
        f"{'READY' if status.tool_agent_ready else 'NOT READY'}"
    )
    if status.health_error:
        print(f"Health check: {safe_text(status.health_error)}")
    if status.capabilities_error:
        print(f"Capabilities check: {safe_text(status.capabilities_error)}")


def _print_case(index: int, total: int, case: dict, result: CaseResult) -> None:
    print(f"\n[{index}/{total}] {case['title']}")
    print(result.status.upper())
    if result.answer_excerpt:
        print(f"Answer: {result.answer_excerpt}")
    if case["mode"] == "basic_rag":
        print(f"Sources: {result.evidence_count}")
    elif case["mode"] == "agentic_rag":
        print(f"Status: {safe_text((result.safe_summary.split(' ')[0]).split('=', 1)[-1])}")
        print(f"Query type: {safe_text(result.query_type)}")
        print(f"Route: {safe_text(result.route)}")
        print(f"Evidence: {result.evidence_count}")
    else:
        print(f"Tools: {', '.join(result.tool_names) or 'none'}")
        if result.observational:
            expected = case.get("expected", {}).get("expected_tool_sequence", [])
            print(f"Expected tool sequence: {', '.join(expected) or 'none'}")
            print(
                "Actual tool sequence: "
                f"{', '.join(result.actual_tool_sequence) or 'none'}"
            )
    if result.error:
        print(f"Reason: {safe_text(result.error)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the live Release 1.0 demo harness")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        print("DEEPSEEK_API_KEY is required for live demo")
        return 2

    try:
        cases = load_cases()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"LIVE DEMO FAILED — {safe_text(exc)}")
        return 1

    print("=" * 48)
    print("RAG Agent — Release 1.0 Demo")
    print("=" * 48)
    client = DemoHttpClient(args.base_url)
    status = preflight(client)
    _print_preflight(status)

    results: list[CaseResult] = []
    if status.health_ok and status.capabilities_ok and status.pipeline_ready:
        try:
            uploaded = upload_fixtures(client)
            print(f"\n[Knowledge] Uploaded: {', '.join(uploaded)}")
        except DemoApiError as exc:
            print(f"LIVE DEMO FAILED — {safe_text(exc)}")
            return 1
    else:
        print("\n[Knowledge] SKIPPED — backend pipeline is not ready")

    for index, case in enumerate(cases, start=1):
        result = run_case(client, case, status)
        results.append(result)
        _print_case(index, len(cases), case, result)

    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        write_artifact(args.output, build_artifact(results, source_commit(), timestamp))
        print(f"\nArtifact: {display_artifact_path(args.output)}")
    except OSError as exc:
        print(f"LIVE DEMO FAILED — artifact write failed: {safe_text(exc)}")
        return 1

    required_results = [result for result in results if result.required]
    passed = sum(result.status == "pass" for result in results)
    failed = sum(result.status == "fail" for result in required_results)
    skipped_required = sum(result.status == "skipped" for result in required_results)
    print("\n" + "=" * 48)
    print("Demo Summary")
    print("=" * 48)
    print(f"Required cases: {len(required_results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Skipped required: {skipped_required}")
    print("Observational: multi-step")
    return 1 if failed or skipped_required else 0


if __name__ == "__main__":
    sys.exit(main())
