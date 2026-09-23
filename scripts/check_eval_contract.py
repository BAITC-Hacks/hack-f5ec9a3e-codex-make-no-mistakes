"""Run mechanics and contract checks with the locked backend environment."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/tests"))

from evaluation.checks import check  # noqa: E402

if __name__ == "__main__":
    check()
    print("Evaluation contracts/mechanics: OK (synthetic checks; not measured app impact)")
