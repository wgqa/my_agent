"""Task 018-Live serial, cross-process budget gate.

This is deliberately scoped to the fixed Task 018 experiment. It persists the
reservation before a request and the response/usage before returning it to the
Agent Runtime. The credential and HTTP headers are never accepted or stored.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from typing import Any
from uuid import uuid4


EXPECTED_MODEL = "deepseek-flash"
INPUT_PEAK_USD_PER_M = 0.30
OUTPUT_PEAK_USD_PER_M = 1.20


class BudgetGateStop(RuntimeError):
    """Fail-closed stop with a short, credential-free reason code."""


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"unsupported request value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=_json_default)


def estimate_input_tokens(request_payload: dict[str, Any]) -> int:
    """Conservative preflight estimate; exact provider usage remains authoritative.

    DeepSeek's model tokenizer is not asserted to equal cl100k_base. We add a
    35% reserve and message overhead; after each response, actual usage is
    persisted and checked against the hard software thresholds.
    """
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        messages = request_payload.get("messages", [])
        text = canonical_json(request_payload)
        estimated = len(encoding.encode(text, disallowed_special=()))
        overhead = 8 * len(messages) + 32
        return int(math.ceil(estimated * 1.35)) + overhead
    except Exception as exc:
        raise BudgetGateStop("TOKEN_ESTIMATOR_UNAVAILABLE") from None


class SharedBudgetGate:
    """Durable shared accounting for the fixed Task 019 serial schedule."""

    def __init__(self, path: Path, *, run_id: str, max_requests: int = 60,
                 max_tokens: int = 200_000, max_estimated_usd: float = 0.15,
                 expected_model: str = EXPECTED_MODEL) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self.max_requests = int(max_requests)
        self.max_tokens = int(max_tokens)
        self.max_estimated_usd = float(max_estimated_usd)
        self.expected_model = expected_model
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _initialize(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS budget_state (
                        singleton INTEGER PRIMARY KEY CHECK (singleton=1),
                        run_id TEXT NOT NULL,
                        max_requests INTEGER NOT NULL,
                        max_tokens INTEGER NOT NULL,
                        max_estimated_usd REAL NOT NULL,
                        expected_model TEXT NOT NULL,
                        requests_reserved INTEGER NOT NULL DEFAULT 0,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        estimated_usd REAL NOT NULL DEFAULT 0,
                        stopped INTEGER NOT NULL DEFAULT 0,
                        stop_reason TEXT,
                        billing_unknown INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS provider_calls (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        call_id TEXT NOT NULL UNIQUE,
                        run_id TEXT NOT NULL,
                        task_order INTEGER NOT NULL,
                        case_id TEXT NOT NULL,
                        variant TEXT NOT NULL,
                        role TEXT NOT NULL,
                        request_model TEXT NOT NULL,
                        prompt_sha256 TEXT NOT NULL,
                        request_sha256 TEXT NOT NULL,
                        request_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        reserved_input_tokens INTEGER NOT NULL,
                        reserved_output_tokens INTEGER NOT NULL,
                        reserved_cost_usd REAL NOT NULL,
                        response_model TEXT,
                        response_json TEXT,
                        prompt_tokens INTEGER,
                        completion_tokens INTEGER,
                        total_tokens INTEGER,
                        estimated_cost_usd REAL,
                        latency_ms REAL,
                        error_category TEXT,
                        billing_status TEXT NOT NULL DEFAULT 'pending',
                        created_at TEXT NOT NULL,
                        completed_at TEXT
                    );
                """)
                state = conn.execute("SELECT * FROM budget_state WHERE singleton=1").fetchone()
                now = self._now()
                if state is None:
                    conn.execute("""INSERT INTO budget_state
                        (singleton,run_id,max_requests,max_tokens,max_estimated_usd,
                         expected_model,updated_at) VALUES (1,?,?,?,?,?,?)""",
                        (self.run_id, self.max_requests, self.max_tokens,
                         self.max_estimated_usd, self.expected_model, now))
                else:
                    identity = (state["run_id"], state["max_requests"], state["max_tokens"],
                                round(state["max_estimated_usd"], 8), state["expected_model"])
                    expected = (self.run_id, self.max_requests, self.max_tokens,
                                round(self.max_estimated_usd, 8), self.expected_model)
                    if identity != expected:
                        raise BudgetGateStop("BUDGET_DATABASE_IDENTITY_MISMATCH")
        except BudgetGateStop:
            raise
        except Exception:
            raise BudgetGateStop("BUDGET_PERSISTENCE_UNAVAILABLE") from None
    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def _valid_usage(usage: dict[str, Any] | None) -> tuple[int, int, int] | None:
        if not isinstance(usage, dict):
            return None
        names = ("prompt_tokens", "completion_tokens", "total_tokens")
        values = [usage.get(name) for name in names]
        if any(type(value) is not int or value < 0 for value in values):
            return None
        prompt, completion, total = values
        if total != prompt + completion:
            return None
        return prompt, completion, total

    def reserve(self, *, task_order: int, case_id: str, variant: str, role: str,
                request_model: str, request_payload: dict[str, Any],
                output_cap: int) -> int:
        if request_model != self.expected_model:
            raise BudgetGateStop("REQUEST_MODEL_MISMATCH")
        if type(output_cap) is not int or output_cap <= 0:
            raise BudgetGateStop("INVALID_OUTPUT_RESERVATION")
        prompt_messages = request_payload.get("messages", [])
        prompt_json = canonical_json(prompt_messages)
        request_json = canonical_json(request_payload)
        prompt_sha = hashlib.sha256(prompt_json.encode("utf-8")).hexdigest()
        request_sha = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        input_reserve = estimate_input_tokens(request_payload)
        reserve_cost = (input_reserve * INPUT_PEAK_USD_PER_M
                        + output_cap * OUTPUT_PEAK_USD_PER_M) / 1_000_000
        now = self._now()
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                state = conn.execute("SELECT * FROM budget_state WHERE singleton=1").fetchone()
                if state["stopped"]:
                    raise BudgetGateStop(state["stop_reason"] or "BUDGET_GATE_STOPPED")
                pending = conn.execute(
                    "SELECT 1 FROM provider_calls WHERE status='reserved' LIMIT 1").fetchone()
                if pending:
                    raise BudgetGateStop("PRIOR_PROVIDER_RESULT_UNRESOLVED")
                if state["requests_reserved"] >= self.max_requests:
                    raise BudgetGateStop("PROVIDER_REQUEST_BUDGET_STOP")
                projected_tokens = (state["input_tokens"] + state["output_tokens"]
                                    + input_reserve + output_cap)
                if projected_tokens > self.max_tokens:
                    raise BudgetGateStop("TOKEN_BUDGET_STOP")
                if state["estimated_usd"] + reserve_cost > self.max_estimated_usd:
                    raise BudgetGateStop("ESTIMATED_COST_BUDGET_STOP")
                call_id = str(uuid4())
                cur = conn.execute("""INSERT INTO provider_calls
                    (call_id,run_id,task_order,case_id,variant,role,request_model,
                     prompt_sha256,request_sha256,request_json,status,
                     reserved_input_tokens,reserved_output_tokens,reserved_cost_usd,
                     billing_status,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,'reserved',?,?,?,'pending',?)""",
                    (call_id, self.run_id, task_order, case_id, variant, role,
                     request_model, prompt_sha, request_sha, request_json,
                     input_reserve, output_cap, reserve_cost, now))
                seq = int(cur.lastrowid)
                conn.execute("""UPDATE budget_state SET requests_reserved=requests_reserved+1,
                    updated_at=? WHERE singleton=1""", (now,))
                conn.commit()
                return seq
        except BudgetGateStop:
            raise
        except Exception:
            raise BudgetGateStop("BUDGET_PERSISTENCE_UNAVAILABLE") from None

    def record_response(self, *, seq: int, response_model: str | None,
                        response_payload: dict[str, Any], usage: dict[str, Any] | None,
                        latency_ms: float) -> str | None:
        usage_tuple = self._valid_usage(usage)
        response_json = canonical_json(response_payload)
        now = self._now()
        stop_reason: str | None = None
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                call = conn.execute("SELECT * FROM provider_calls WHERE seq=?", (seq,)).fetchone()
                if call is None or call["status"] != "reserved":
                    raise BudgetGateStop("PROVIDER_RECORD_STATE_INVALID")
                state = conn.execute("SELECT * FROM budget_state WHERE singleton=1").fetchone()
                if usage_tuple is None:
                    stop_reason = "PROVIDER_USAGE_MISSING_OR_INCONSISTENT"
                    conn.execute("""UPDATE provider_calls SET status='usage_invalid',
                        response_model=?,response_json=?,latency_ms=?,error_category=?,
                        billing_status='unknown',completed_at=? WHERE seq=?""",
                        (response_model, response_json, float(latency_ms), stop_reason, now, seq))
                    conn.execute("""UPDATE budget_state SET stopped=1,stop_reason=?,
                        billing_unknown=1,updated_at=? WHERE singleton=1""", (stop_reason, now))
                else:
                    prompt_tokens, completion_tokens, total_tokens = usage_tuple
                    cost = (prompt_tokens * INPUT_PEAK_USD_PER_M
                            + completion_tokens * OUTPUT_PEAK_USD_PER_M) / 1_000_000
                    identity_bad = response_model != self.expected_model
                    new_input = state["input_tokens"] + prompt_tokens
                    new_output = state["output_tokens"] + completion_tokens
                    new_cost = state["estimated_usd"] + cost
                    if identity_bad:
                        stop_reason = "RESPONSE_MODEL_IDENTITY_MISMATCH"
                    elif new_input + new_output > self.max_tokens:
                        stop_reason = "TOKEN_BUDGET_STOP_AFTER_RESPONSE"
                    elif new_cost > self.max_estimated_usd:
                        stop_reason = "ESTIMATED_COST_BUDGET_STOP_AFTER_RESPONSE"
                    status = "response_identity_mismatch" if identity_bad else "response_recorded"
                    conn.execute("""UPDATE provider_calls SET status=?,response_model=?,
                        response_json=?,prompt_tokens=?,completion_tokens=?,total_tokens=?,
                        estimated_cost_usd=?,latency_ms=?,billing_status='known',error_category=?,
                        completed_at=? WHERE seq=?""",
                        (status, response_model, response_json, prompt_tokens,
                         completion_tokens, total_tokens, cost, float(latency_ms),
                         stop_reason, now, seq))
                    conn.execute("""UPDATE budget_state SET input_tokens=?,output_tokens=?,
                        estimated_usd=?,stopped=?,stop_reason=?,updated_at=? WHERE singleton=1""",
                        (new_input, new_output, new_cost, int(stop_reason is not None),
                         stop_reason, now))
                conn.commit()
        except BudgetGateStop:
            raise
        except Exception:
            raise BudgetGateStop("BUDGET_PERSISTENCE_UNAVAILABLE") from None
        return stop_reason

    def record_provider_error(self, *, seq: int, error_category: str,
                              latency_ms: float) -> None:
        now = self._now()
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                call = conn.execute("SELECT status FROM provider_calls WHERE seq=?", (seq,)).fetchone()
                if call is None or call["status"] != "reserved":
                    raise BudgetGateStop("PROVIDER_RECORD_STATE_INVALID")
                conn.execute("""UPDATE provider_calls SET status='provider_error',
                    error_category=?,latency_ms=?,billing_status='unknown',completed_at=?
                    WHERE seq=?""", (error_category, float(latency_ms), now, seq))
                conn.execute("""UPDATE budget_state SET stopped=1,
                    stop_reason='PROVIDER_ERROR_BILLING_UNKNOWN',billing_unknown=1,
                    updated_at=? WHERE singleton=1""", (now,))
                conn.commit()
        except BudgetGateStop:
            raise
        except Exception:
            raise BudgetGateStop("BUDGET_PERSISTENCE_UNAVAILABLE") from None

    def stop(self, reason: str, *, billing_unknown: bool = False) -> None:
        now = self._now()
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("""UPDATE budget_state SET stopped=1,stop_reason=?,
                    billing_unknown=MAX(billing_unknown,?),updated_at=? WHERE singleton=1""",
                    (reason, int(billing_unknown), now))
                conn.commit()
        except Exception:
            raise BudgetGateStop("BUDGET_PERSISTENCE_UNAVAILABLE") from None

    def snapshot(self) -> dict[str, Any]:
        try:
            with self._connect() as conn:
                state = conn.execute("SELECT * FROM budget_state WHERE singleton=1").fetchone()
                counts = conn.execute("SELECT status,COUNT(*) AS n FROM provider_calls GROUP BY status").fetchall()
                pending = conn.execute("SELECT COUNT(*) FROM provider_calls WHERE status='reserved'").fetchone()[0]
                return {
                    "run_id": state["run_id"],
                    "requests_reserved": state["requests_reserved"],
                    "input_tokens": state["input_tokens"],
                    "output_tokens": state["output_tokens"],
                    "total_tokens": state["input_tokens"] + state["output_tokens"],
                    "estimated_usd": round(state["estimated_usd"], 8),
                    "stopped": bool(state["stopped"]),
                    "stop_reason": state["stop_reason"],
                    "billing_unknown": bool(state["billing_unknown"]),
                    "pending_provider_results": int(pending),
                    "call_status_counts": {row["status"]: row["n"] for row in counts},
                    "limits": {"requests": state["max_requests"],
                               "tokens": state["max_tokens"],
                               "estimated_usd": state["max_estimated_usd"]},
                    "expected_model": state["expected_model"],
                }
        except Exception:
            raise BudgetGateStop("BUDGET_PERSISTENCE_UNAVAILABLE") from None

    def export_calls_jsonl(self, output_path: Path) -> None:
        """Export committed request/response records atomically; no headers/keys."""
        output_path = Path(output_path)
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM provider_calls ORDER BY seq").fetchall()
                tmp = output_path.with_suffix(output_path.suffix + ".tmp")
                with tmp.open("w", encoding="utf-8", newline="\n") as stream:
                    for row in rows:
                        item = dict(row)
                        item["request"] = json.loads(item.pop("request_json"))
                        response_json = item.pop("response_json")
                        item["response"] = json.loads(response_json) if response_json else None
                        stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp, output_path)
        except Exception:
            raise BudgetGateStop("BUDGET_PERSISTENCE_UNAVAILABLE") from None
