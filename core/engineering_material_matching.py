"""Matcher v2: actual objects and returned ranges, never semantic approval.

Reader v5 certifies the identity of its loaded file. Coverage uses ONLY body
lines actually returned; AST locations do not supply missing source content.
The old matcher is deliberately retained for records without that identity.
"""
from collections import defaultdict
import json
import re

from core.engineering_materials import ToolResultEvidence
from core.tool_agent.project_files import classify_project_evidence_path
from core.tool_agent.runtime_models import EngineeringEvidence

MATERIAL_MATCHER_VERSION = "engineering_material_matcher_v2"


def _objects(goal, record):
    objects = record.details.get("objects", ())
    symbol = goal.target.symbol
    matched = []
    for item in objects:
        span = item["definition"]
        if not (record.evidence.start_line <= span["end_line"]
                and record.evidence.end_line >= span["start_line"]):
            continue
        if symbol:
            if "." in symbol:
                if span["name"] != symbol or not item["qualified_name_unique"]:
                    continue
            elif span["name"].rsplit(".", 1)[-1] != symbol or not item["short_name_unique"]:
                continue
        elif goal.depth == "implementation":
            # An unspecified implementation needs an explicitly selected object;
            # seeing arbitrary functions in a file is not object resolution.
            selected = [t.get("definition") for t in record.details.get("targets", ())]
            if span not in selected:
                continue
        if goal.depth == "implementation" and span["kind"] not in {"function", "class"}:
            continue
        matched.append(span)
    return matched


def _body_identity(goal, record):
    if (type(record.evidence) is not EngineeringEvidence or record.form != "body"
            or not set(goal.source_kinds).intersection(record.source_kinds)
            or (goal.target.path and record.evidence.path != goal.target.path)):
        return False
    snapshot = record.details.get("source_snapshot")
    if snapshot is None:
        return False
    request = record.details.get("request", {})
    for field, argument in (("change_mode", "mode"), ("base_ref", "base_ref"), ("head_ref", "head_ref")):
        value = getattr(goal.target, field)
        if value is not None and request.get(argument) != value:
            return False
    if (goal.target.symbol or goal.depth == "implementation") and not _objects(goal, record):
        # An actual ambiguity response supplies candidate *locations*, never
        # permission to choose one arbitrary body as the requested implementation.
        ambiguity = goal.depth == "locator" and any(
            target.get("requested") == goal.target.symbol and target.get("status") == "ambiguous"
            and len(target.get("candidates", ())) > 1
            for target in record.details.get("selection_targets", ()))
        if not ambiguity:
            return False
    return True


def _usable_range(record):
    details = record.details
    reasons = set(details.get("truncation_reasons", ()))
    for target in details.get("targets", ()):
        reasons.update(target.get("truncation_reasons", ()))
    # Line/character *page* limits do not clip returned lines. A clipped
    # individual line cannot be repaired by a page containing later lines.
    return not ("line_length_limit" in reasons or details.get("omitted_sensitive_count", 0)
                or details.get("selection_truncated"))


def _complete_ids(goal, records):
    groups = defaultdict(list)
    for record in records:
        if not _usable_range(record):
            continue
        snapshot = record.details["source_snapshot"]
        provenance = json.loads(record.provenance_json)
        binding = provenance.get("binding_identity")
        if goal.target.symbol or goal.depth == "implementation":
            scopes = [(s["name"], s["kind"], s["start_line"], s["end_line"]) for s in _objects(goal, record)]
        else:
            scopes = [("file", "file", 1, snapshot["line_count"])]
        for name, kind, start, end in scopes:
            # Without a binding identity, only a single self-contained body is
            # certifiable; unrelated run records must never be stitched.
            identity = (binding or record.evidence.evidence_id, record.evidence.path,
                        snapshot["content_sha256"], name, kind, start, end)
            groups[identity].append(record)
    ids = []
    for identity, parts in groups.items():
        required_start, required_end = identity[-2:]
        cursor = required_start
        for record in sorted(parts, key=lambda r: (r.evidence.start_line, r.evidence.end_line)):
            start, end = record.evidence.start_line, record.evidence.end_line
            if end < cursor:
                continue
            if start > cursor:
                break
            cursor = max(cursor, end+1)
        if cursor > required_end:
            ids.extend(r.evidence.evidence_id for r in parts)
    return tuple(dict.fromkeys(ids))


def goal_material_ids(goal, records):
    """Candidate support IDs, with full ranges requiring an actual union proof."""
    from core.engineering_candidate_verification import material_matches_goal
    records = tuple(records)
    ids, bodies = [], []
    for record in records:
        if goal.depth in {"body", "implementation", "locator"} and record.form == "body" and "source_snapshot" in record.details:
            if _body_identity(goal, record):
                if goal.full_range:
                    bodies.append(record)
                else:
                    ids.append(record.evidence.evidence_id)
            continue
        if goal.depth == "locator" and type(record.evidence) is ToolResultEvidence and record.evidence.tool_name == "code_search":
            if goal.full_range:
                continue  # Bounded literal search cannot certify all locations.
            # Literal locations are candidates, not AST qualification proofs.
            # Qualified ownership still needs body metadata / semantic review.
            token = (goal.target.symbol.rsplit(".", 1)[-1] if goal.target.symbol else goal.target.query)
            for hit in record.evidence.payload["matches"]:
                if (goal.target.path and hit["path"] != goal.target.path
                        or classify_project_evidence_path(hit["path"]) not in goal.source_kinds):
                    continue
                token_matches = (re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", hit["text"], re.IGNORECASE)
                                 if token and goal.target.symbol else
                                 (not token or token.casefold() in hit["text"].casefold()))
                if not token_matches:
                    continue
                ids.append(record.evidence.evidence_id)
                break
            continue
        if material_matches_goal(goal, record):
            ids.append(record.evidence.evidence_id)
    ids.extend(_complete_ids(goal, bodies))
    return tuple(dict.fromkeys(ids))
