"""Replay frozen real Reader observations through the public excerpt converter.

No model requests, answers or old records are changed. This measures excerpt
fidelity and identity, not the semantic quality of a newly generated answer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace


ARCHIVE = Path(__file__).resolve().parent
REPO = ARCHIVE.parents[1]
sys.path.insert(0, str(REPO))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), "Use a fresh output file"

    from api.schemas import ToolAgentEvidence
    from core.tool_agent.default_tools import build_readonly_tool_registry
    from core.tool_agent.decision_prompt import compute_toolset_sha256
    from core.tool_agent.runtime import _evidence_from_project_context
    from core.tool_agent.runtime_models import ToolAgentBudget
    from core.tool_agent.source_excerpt import MAX_PROJECT_CONTEXT_CHARACTERS

    manifest = json.loads((ARCHIVE / "initial_manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["previous_archive_sha256"].items():
        assert sha(REPO / name) == expected, name
    for name, expected in manifest["protected_files_sha256"].items():
        assert sha(REPO / name) == expected, name
    for name, expected in manifest["baseline_file_sha256"].items():
        assert sha(ARCHIVE / "baseline" / name) == expected, name

    class EmptyPort:
        supported_strategies = ("bm25", "hybrid")

        def search(self, *_args):
            return ()

    registry = build_readonly_tool_registry(REPO, EmptyPort())
    assert compute_toolset_sha256(registry.list_specs()) == manifest["baseline_toolset_sha256"]
    engineering_hash = compute_toolset_sha256([s for s in registry.list_specs() if s.name != "knowledge_search"])
    assert engineering_hash == "30846e05d9fbead31244a262d3b6bf1d6429fcdc5528316428810e5dd6c189ab"
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)

    ci = re.findall(r"tests/test_[A-Za-z0-9_]+\.py", (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    blocks = re.findall(r"```bash\n(.*?)```", (REPO / "docs/release2_local_runbook.md").read_text(encoding="utf-8"), re.DOTALL)
    documented = next(re.findall(r"tests/test_[A-Za-z0-9_]+\.py", block) for block in blocks if "tests/test_tool_agent_core.py" in block)
    assert ci == documented and len(ci) == len(set(ci)) == 36

    reads = []
    request_count = 0
    affected_requests = set()
    for phase in ("", "document_source_slice"):
        path = REPO / "evaluation/task_completion_20261003" / phase / "raw/paired/live_results.jsonl"
        for row in map(json.loads, path.read_text(encoding="utf-8").splitlines()):
            request_count += 1
            for event in row["observations"]:
                if event["stage"] != "source_read" or event["status"] != "ok":
                    continue
                result = event["result"]
                expected = "\n".join(line["text"] for line in result["lines"])
                new = _evidence_from_project_context(SimpleNamespace(status="ok", tool_name="read_project_context", result=result))
                assert new is not None and new.snippet == expected
                assert (new.path, new.start_line, new.end_line) == (result["path"], result["start_line"], result["end_line"])
                old = next(item for item in row["public_response"]["evidence"] if item.get("path") == new.path and item.get("start_line") == new.start_line and item.get("end_line") == new.end_line)
                assert old["snippet"] == expected[:2000]
                payload = new.to_dict()
                payload["evidence_id"] = old["evidence_id"]
                assert ToolAgentEvidence(**payload).model_dump() == payload
                clipped = old["snippet"] != expected
                if clipped:
                    affected_requests.add((phase, row["id"], row["arm"]))
                reads.append({
                    "phase": phase or "prompt", "id": row["id"], "arm": row["arm"],
                    "evidence_id": old["evidence_id"], "kind": new.kind,
                    "path": new.path, "start_line": new.start_line, "end_line": new.end_line,
                    "observed_characters": len(expected), "before_characters": len(old["snippet"]), "after_characters": len(new.snippet),
                    "before_clipped": clipped, "after_matches_actual_read": True,
                    "public_identity_unchanged": True, "actual_text_sha256": hashlib.sha256(expected.encode("utf-8")).hexdigest(),
                })
    assert request_count == 48
    report = {
        "provider_calls": 0, "historical_user_requests_inspected": request_count,
        "successful_reads_replayed": len(reads), "before_clipped_reads": sum(r["before_clipped"] for r in reads),
        "before_affected_requests": len(affected_requests), "after_clipped_reads": 0,
        "maximum_observed_characters": max(r["observed_characters"] for r in reads),
        "public_read_character_cap": MAX_PROJECT_CONTEXT_CHARACTERS,
        "protected_files_unchanged": len(manifest["protected_files_sha256"]),
        "previous_archive_files_unchanged": len(manifest["previous_archive_sha256"]),
        "toolset_sha256": {"all_readonly_tools": manifest["baseline_toolset_sha256"], "engineering_without_knowledge_search": engineering_hash},
        "ci_runbook_lists_identical": True, "ci_test_files": len(ci),
        "answer_quality_claim": "None: frozen answers are not regenerated or regraded; this only tests public excerpt fidelity.",
        "reads": reads,
    }
    args.output.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({k: v for k, v in report.items() if k not in ("reads", "toolset_sha256")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
