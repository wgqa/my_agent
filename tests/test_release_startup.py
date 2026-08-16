"""G5-RUN-04: real process-level API startup smoke.

pytest 测的与用户手工执行的是同一条启动 smoke：直接调用
`python scripts/smoke_local_api.py`（真实 uvicorn 子进程、临时 cwd、
dummy key、offline HF），断言 exit code == 0。

启动 smoke 只证明"能启动 + /health 可访问 + OpenAPI 暴露预期路由"，
不调用 DeepSeek / OpenAI / 不下载模型 / 不访问公网。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE = REPO_ROOT / "scripts" / "smoke_local_api.py"


def test_startup_smoke_exit_zero():
    """真实 uvicorn 进程启动 + /health + /openapi 验证必须成功。"""
    result = subprocess.run(
        [sys.executable, str(SMOKE)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"startup smoke failed rc={result.returncode}\n"
        f"--- stdout ---\n{result.stdout[-2000:]}\n"
        f"--- stderr ---\n{result.stderr[-2000:]}"
    )
    assert "STARTUP_SMOKE_OK" in result.stdout
