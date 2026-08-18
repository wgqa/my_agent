"""G5-RUN-05: real FastAPI + Streamlit integration smoke."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE = REPO_ROOT / "scripts" / "smoke_local_app.py"


def test_full_app_smoke_exit_zero():
    """The release smoke must execute the real UI against a live backend."""
    result = subprocess.run(
        [sys.executable, str(SMOKE)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"full app smoke failed rc={result.returncode}\n"
        f"--- stdout ---\n{result.stdout[-4000:]}\n"
        f"--- stderr ---\n{result.stderr[-4000:]}"
    )
    assert "FULL_APP_SMOKE_OK" in result.stdout
