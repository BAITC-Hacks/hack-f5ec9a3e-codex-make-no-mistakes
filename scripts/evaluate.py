"""Generate the real-data inventory evaluation readiness report (no database)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/tests"))

from evaluation.runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
