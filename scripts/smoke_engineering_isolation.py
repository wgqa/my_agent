"""Real uvicorn + Streamlit AppTest with an intentionally broken legacy config.

Requires the existing verified corpus. Uses dummy keys and isolated workspace/DB;
no query is sent to Engineering and no model, embedding or network API is called.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error

from smoke_local_api import (
    REPO_ROOT, READY_TIMEOUT_SECONDS, _build_env, _drain, _free_port,
    _http_get, _terminate,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    args = parser.parse_args()
    corpus = args.corpus_root.resolve(strict=True)
    base = f"http://127.0.0.1:{_free_port()}"
    with tempfile.TemporaryDirectory(prefix="engineering_isolation_") as temporary:
        temporary = Path(temporary)
        (temporary / "config.yaml").write_text("embedding:\n  provider: deliberately_invalid\n", encoding="utf-8")
        project = temporary / "project"
        project.mkdir()
        env = _build_env(temporary)
        env["ENGINEERING_PROJECT_ROOT"] = str(project)
        env["ENGINEERING_CONVERSATION_DB"] = str(temporary / "conversations.sqlite3")
        env["ENGINEERING_KNOWLEDGE_CORPUS_ROOT"] = str(corpus)
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.app:app", "--host", "127.0.0.1",
             "--port", base.rsplit(":", 1)[1], "--log-level", "error"],
            cwd=temporary, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            capabilities = None
            deadline = time.monotonic() + READY_TIMEOUT_SECONDS
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    _, capabilities = _http_get(base + "/capabilities", timeout=2)
                    break
                except (urllib.error.URLError, OSError):
                    time.sleep(.25)
            if capabilities is None:
                raise AssertionError("capabilities did not become reachable")
            assert capabilities["pipeline_ready"] is False
            assert capabilities["agent_runtime_ready"] is False
            assert capabilities["tool_agent_runtime_ready"] is False
            assert capabilities["features"]["engineering_agent"] is True
            _, knowledge = _http_get(base + "/engineering/knowledge")
            assert knowledge["ready"] and knowledge["verified"]
            assert (knowledge["corpus_id"], knowledge["file_count"], knowledge["chunk_count"]) == ("870e5864df67", 37, 215)
            try:
                _http_get(base + "/health")
            except urllib.error.HTTPError as error:
                assert error.code == 503
            else:
                raise AssertionError("legacy health unexpectedly succeeded")

            # Execute the actual page against the live HTTP server. No chat
            # input is submitted, so dummy credentials cannot reach a provider.
            from streamlit.testing.v1 import AppTest
            previous_url = os.environ.get("RAG_API_URL")
            os.environ["RAG_API_URL"] = base
            try:
                if str(REPO_ROOT) not in sys.path:
                    sys.path.insert(0, str(REPO_ROOT))
                page = AppTest.from_file(str(REPO_ROOT / "ui/app.py"), default_timeout=30).run()
                assert not page.exception
                assert page.session_state["api_available"] is True
                assert page.session_state["runtime_health"] is None
                assert page.session_state["runtime_capabilities"]["features"]["engineering_agent"] is True
                assert len(page.chat_input) == 1 and page.chat_input[0].disabled is False
            finally:
                if previous_url is None:
                    os.environ.pop("RAG_API_URL", None)
                else:
                    os.environ["RAG_API_URL"] = previous_url
            print("ENGINEERING_ISOLATION_SMOKE_OK")
            print("legacy_pipeline=false; engineering_verified=true; ui_chat_available=true")
            print("provider_calls=0; embedding_calls=0; isolated_workspace_and_db=true")
            return 0
        except Exception as error:
            print(f"ENGINEERING_ISOLATION_SMOKE_FAILED: {type(error).__name__}", file=sys.stderr)
            return 1
        finally:
            _terminate(process)
            _drain(process)


if __name__ == "__main__":
    raise SystemExit(main())
