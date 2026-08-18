"""G5-RUN-05 full local application integration smoke.

This smoke starts the real FastAPI process and the real Streamlit server in
isolated, offline conditions.  It then executes ``ui/app.py`` with
``streamlit.testing.v1.AppTest`` while ``RAG_API_URL`` points at that live
FastAPI process.  No query endpoint is called, so no LLM, planner, embedding,
or tool-agent work is required.

Usage::

    python scripts/smoke_local_app.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from smoke_local_api import (
    CONFIG_YAML,
    READY_TIMEOUT_SECONDS,
    _build_env,
    _drain,
    _free_port,
    _http_get,
    _redact,
    _terminate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_FILE = REPO_ROOT / "ui" / "app.py"
POLL_INTERVAL = 0.5

# Direct script execution puts only ``scripts/`` on sys.path.  AppTest runs
# the page in this process, so make the repository package imports explicit.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _http_status(url: str, timeout: float = 5.0) -> int:
    """Return an HTTP status without assuming the body is JSON."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status


def _wait_for_status(proc, url: str, expected: int) -> tuple[bool, str]:
    deadline = time.time() + READY_TIMEOUT_SECONDS
    diagnostics = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            diagnostics = _drain(proc)
            break
        try:
            if _http_status(url, timeout=2) == expected:
                return True, diagnostics
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(POLL_INTERVAL)
    return False, diagnostics


def _assert_app_test(backend_base: str) -> None:
    """Execute the page and check only non-query integration behavior."""
    from streamlit.testing.v1 import AppTest

    previous_url = os.environ.get("RAG_API_URL")
    os.environ["RAG_API_URL"] = backend_base
    try:
        app_test = AppTest.from_file(str(APP_FILE), default_timeout=15)
        app_test.run(timeout=30)

        if len(app_test.exception) > 0:
            details = "\n".join(str(item) for item in app_test.exception)
            raise AssertionError(f"Streamlit AppTest exception: {details}")

        titles = [getattr(item, "value", "") for item in app_test.title]
        if not any("RAG Agent Demo Console" in title for title in titles):
            raise AssertionError(f"page title missing: {titles!r}")

        successes = [getattr(item, "value", "") for item in app_test.success]
        if not any("服务正常" in value for value in successes):
            raise AssertionError(f"sidebar did not report backend online: {successes!r}")

        captions = [getattr(item, "value", "") for item in app_test.caption]
        config_caption = " ".join(captions)
        for provider in ("bge", "hybrid", "deepseek"):
            if provider not in config_caption:
                raise AssertionError(
                    f"health configuration was not rendered ({provider!r}): "
                    f"{config_caption!r}"
                )

        metrics = [getattr(item, "label", "") for item in app_test.metric]
        if "文档块总数" not in metrics:
            raise AssertionError(f"stats was not rendered: {metrics!r}")

        tabs = [getattr(item, "label", "") for item in app_test.tabs]
        for required_tab in ("知识库", "Agent Console"):
            if not any(required_tab in label for label in tabs):
                raise AssertionError(f"missing tab {required_tab!r}: {tabs!r}")

        if len(app_test.radio) == 0:
            raise AssertionError("mode radio is missing")
        modes = list(app_test.radio[0].options)
        required_modes = (
            "Basic RAG",
            "Agentic RAG",
            "Structured Tool Agent",
        )
        if not all(mode in modes for mode in required_modes):
            raise AssertionError(f"required modes missing: {modes!r}")

        # Mode changes rerun only health/stats; no query endpoint is submitted.
        for mode in required_modes:
            app_test.radio[0].set_value(mode).run(timeout=30)
            if len(app_test.exception) > 0:
                details = "\n".join(str(item) for item in app_test.exception)
                raise AssertionError(f"mode {mode!r} raised: {details}")
            slider_labels = [getattr(item, "label", "") for item in app_test.slider]
            has_top_k = any("top_k" in label or "检索数量" in label for label in slider_labels)
            if mode == "Structured Tool Agent" and has_top_k:
                raise AssertionError("tool-agent mode unexpectedly exposes top_k")
            if mode != "Structured Tool Agent" and not has_top_k:
                raise AssertionError(f"{mode!r} does not expose top_k")
    finally:
        if previous_url is None:
            os.environ.pop("RAG_API_URL", None)
        else:
            os.environ["RAG_API_URL"] = previous_url


def main() -> int:
    if not CONFIG_YAML.is_file() or not APP_FILE.is_file():
        print("[FAIL] missing config.yaml or ui/app.py", file=sys.stderr)
        return 1

    backend_port = _free_port()
    streamlit_port = _free_port()
    while streamlit_port == backend_port:
        streamlit_port = _free_port()
    backend_base = f"http://127.0.0.1:{backend_port}"
    backend_proc = None
    streamlit_proc = None

    with tempfile.TemporaryDirectory(prefix="rag_full_app_smoke_") as tmp:
        tmp_dir = Path(tmp)
        shutil.copy2(CONFIG_YAML, tmp_dir / "config.yaml")
        backend_env = _build_env(tmp_dir)
        backend_cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(backend_port),
            "--log-level",
            "warning",
        ]
        streamlit_env = dict(backend_env)
        streamlit_env["RAG_API_URL"] = backend_base
        streamlit_env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
        streamlit_cmd = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(APP_FILE),
            "--server.address",
            "127.0.0.1",
            "--server.port",
            str(streamlit_port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
            "--logger.level",
            "warning",
        ]

        try:
            backend_proc = subprocess.Popen(
                backend_cmd,
                cwd=str(tmp_dir),
                env=backend_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            backend_ready, backend_diag = _wait_for_status(
                backend_proc, f"{backend_base}/health", 200
            )
            if not backend_ready:
                print("[FAIL] backend /health did not return 200", file=sys.stderr)
                if backend_diag:
                    print(_redact(backend_diag[-4000:]), file=sys.stderr)
                return 1

            health_status, health = _http_get(f"{backend_base}/health")
            if health_status != 200:
                print(f"[FAIL] backend health status={health_status}", file=sys.stderr)
                return 1
            stats_status, stats = _http_get(f"{backend_base}/stats")
            if stats_status != 200 or not isinstance(stats.get("config"), dict):
                print("[FAIL] backend /stats did not return config", file=sys.stderr)
                return 1

            streamlit_proc = subprocess.Popen(
                streamlit_cmd,
                cwd=str(tmp_dir),
                env=streamlit_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            streamlit_ready, streamlit_diag = _wait_for_status(
                streamlit_proc,
                f"http://127.0.0.1:{streamlit_port}/_stcore/health",
                200,
            )
            if not streamlit_ready:
                print("[FAIL] Streamlit /_stcore/health did not return 200", file=sys.stderr)
                if streamlit_diag:
                    print(_redact(streamlit_diag[-4000:]), file=sys.stderr)
                return 1

            _assert_app_test(backend_base)

            print("FULL_APP_SMOKE_OK")
            print(f"backend_health={health_status}")
            print("streamlit_health=200")
            print("ui_backend_connection=ok")
            print("required_modes=present")
            return 0
        except (AssertionError, OSError, urllib.error.URLError, ValueError) as exc:
            print(f"[FAIL] {_redact(str(exc))}", file=sys.stderr)
            return 1
        finally:
            if streamlit_proc is not None:
                _terminate(streamlit_proc)
            if backend_proc is not None:
                _terminate(backend_proc)


if __name__ == "__main__":
    sys.exit(main())
