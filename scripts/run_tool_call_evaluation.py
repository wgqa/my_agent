"""Default: zero-model preflight. Real models require an explicit --live flag."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.tool_calls_v2.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
