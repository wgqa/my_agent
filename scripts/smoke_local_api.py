"""G5-RUN-04 local API startup smoke.

启动一个**真实** uvicorn 子进程（不是 TestClient），从临时工作目录运行，
显式 dummy key + 强制 HF 离线，然后验证：

- GET /health -> 200，且 embedding_provider=bge、retriever_strategy=hybrid、
  generator_provider=deepseek
- GET /openapi.json -> 200，且包含 /health /query /agent/query /tool-agent/query

不依赖真实 API key、不依赖模型缓存、不访问任何公网（允许仅 127.0.0.1）。

用法：
    python scripts/smoke_local_api.py [--port PORT]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_YAML = REPO_ROOT / "config.yaml"
READY_TIMEOUT_SECONDS = 60.0
POLL_INTERVAL = 0.5
DUMMY_KEY = "dummy-placeholder-not-a-real-key"
_MAX_DIAG_LINES = 60
_REDACT = re.compile(
    r"(sk-[A-Za-z0-9_-]+|api[_-]?key[^\n]*|authorization[^\n]*)", re.I
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_env(temp_dir: Path) -> dict:
    env = dict(os.environ)
    # 显式覆盖：绝不继承开发者机器上的真实 Key
    env["DEEPSEEK_API_KEY"] = DUMMY_KEY
    env["OPENAI_API_KEY"] = DUMMY_KEY
    # 强制离线 HF：不碰真实模型缓存，也不得从 Hub 下载
    hf_home = temp_dir / "hf_cache"
    env["HF_HOME"] = str(hf_home)
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    # PYTHONPATH 指向 repo root：即使 cwd 是临时目录也能 import api.app
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + existing if existing else "")
    return env


def _http_get(url: str, timeout: float = 5.0) -> tuple[int, dict]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _redact(text: str) -> str:
    return _REDACT.sub("[REDACTED]", text)


def _drain(proc, tail_lines: int = _MAX_DIAG_LINES) -> str:
    try:
        out, err = proc.communicate(timeout=3)
        text = (out or b"") + (err or b"")
    except subprocess.TimeoutExpired:
        text = b""
    return _redact(text.decode("utf-8", "replace"))


def _terminate(proc) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Local API startup smoke")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    if not CONFIG_YAML.is_file():
        print("[FAIL] 未找到仓库 config.yaml", file=sys.stderr)
        return 1

    port = args.port or _free_port()
    base = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory(prefix="rag_smoke_") as tmp:
        tmp_dir = Path(tmp)
        shutil.copy2(CONFIG_YAML, tmp_dir / "config.yaml")
        cmd = [
            sys.executable, "-m", "uvicorn", "api.app:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ]
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(tmp_dir), env=_build_env(tmp_dir),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            print(f"[FAIL] 无法启动 uvicorn 子进程: {exc}", file=sys.stderr)
            return 1

        ready = False
        deadline = time.time() + READY_TIMEOUT_SECONDS
        diag = ""
        while time.time() < deadline:
            if proc.poll() is not None:
                diag = _drain(proc)
                break
            try:
                status, _ = _http_get(f"{base}/health", timeout=2)
                if status == 200:
                    ready = True
                    break
            except (urllib.error.URLError, OSError, json.JSONDecodeError):
                pass
            time.sleep(POLL_INTERVAL)

        if not ready:
            print("[FAIL] uvicorn 未在超时内就绪（/health 未返回 200）", file=sys.stderr)
            if diag:
                print("--- uvicorn 输出（有限，已脱敏） ---", file=sys.stderr)
                print("\n".join(diag.splitlines()[-_MAX_DIAG_LINES:]), file=sys.stderr)
            _terminate(proc)
            return 1

        try:
            h_status, health = _http_get(f"{base}/health")
            if h_status != 200:
                print(f"[FAIL] /health 状态 {h_status}", file=sys.stderr)
                return 1
            expected = {
                "embedding_provider": "bge",
                "retriever_strategy": "hybrid",
                "generator_provider": "deepseek",
            }
            actual = {k: health.get(k) for k in expected}
            bad = [k for k, v in expected.items() if actual[k] != v]
            if bad:
                print(f"[FAIL] /health 字段不符: {bad} 实际={actual}", file=sys.stderr)
                return 1

            o_status, openapi = _http_get(f"{base}/openapi.json")
            if o_status != 200:
                print(f"[FAIL] /openapi.json 状态 {o_status}", file=sys.stderr)
                return 1
            required = ["/health", "/query", "/agent/query", "/tool-agent/query"]
            paths = openapi.get("paths", {})
            missing = [r for r in required if r not in paths]
            if missing:
                print(f"[FAIL] OpenAPI 缺路由: {missing}", file=sys.stderr)
                return 1

            print("STARTUP_SMOKE_OK")
            print(f"health={h_status}")
            print(f"openapi={o_status}")
            print("required_routes=present")
            print("model_network_not_required=true")
            return 0
        finally:
            _terminate(proc)
    # 临时目录自动清理


if __name__ == "__main__":
    sys.exit(main())
