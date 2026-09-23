"""Evaluate the V2 monthly forecast candidates on pinned source workbooks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
sys.path.insert(0, str(ROOT / "backend/tests"))

from evaluation.cases import read_batch  # noqa: E402

from replenishment.calculation.contracts import validate_batch  # noqa: E402
from replenishment.calculation.evaluation import evaluate  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, help="Pinned V2 batch JSON; defaults to source workbooks")
    parser.add_argument("--output", type=Path, help="Write one immutable JSON report")
    parser.add_argument("--development-origin", action="append")
    parser.add_argument("--retrospective-origin", action="append")
    args = parser.parse_args(argv)
    batch = json.loads(args.batch.read_text(encoding="utf-8")) if args.batch else read_batch()
    validate_batch(batch)
    development = args.development_origin or [f"2025-{month:02}-01" for month in range(6, 10)]
    retrospective = args.retrospective_origin or [f"2026-{month:02}-01" for month in range(1, 6)]
    report = evaluate(batch["series"], development, retrospective)
    report.update(
        protocol="monthly-forecast-evaluation-v2",
        planning_date=batch["planning_date"],
        source_selection=batch["source_selection"],
        series_count=len(batch["series"]),
        development_origins=development,
        retrospective_origins=retrospective,
        selection_frozen_before_retrospective=True,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        if args.output.exists():
            raise FileExistsError(args.output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    selected = report["selection_frozen"]
    development_metrics = report["development"]["metrics"].get(selected, {}) if selected else {}
    print(
        json.dumps(
            {
                "protocol": report["protocol"],
                "series": report["series_count"],
                "selected_model": selected,
                "development_primary_error": development_metrics.get("primary_error"),
                "retrospective_primary_error": report.get("retrospective_selected", {}).get("primary_error")
                if report.get("retrospective_selected")
                else None,
                "development_runtime_seconds": report["development"]["runtime_seconds"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
