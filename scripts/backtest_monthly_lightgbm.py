"""Fixed monthly LightGBM comparison; run in experiments/.venv, never production."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/src"), str(ROOT / "backend/tests")]

from evaluation.cases import read_batch  # noqa: E402

from replenishment.calculation.evaluation import _metric, evaluate_origins, promotion_gate  # noqa: E402
from replenishment.calculation.ml import MODEL_CONFIG, evaluate_lightgbm_origins  # noqa: E402


def compare(series, origins, phase):
    stats = evaluate_origins(series, origins, phase=phase)
    ml = evaluate_lightgbm_origins(series, origins, phase=phase)

    def key(row):
        return row["series_id"], row["origin"], row["target_month"]

    predictions = {key(row): row["predictions"]["lightgbm"] for row in ml["rows"]}
    if set(predictions) != {key(row) for row in stats["rows"]}:
        raise ValueError("ML and statistics have different target keys")
    for row in stats["rows"]:
        row["predictions"]["lightgbm"] = predictions[key(row)]
    # Unchanged decimal actuals/scales and identical eligibility for every candidate.
    stats["metrics"]["lightgbm"] = _metric(stats["rows"], "lightgbm")
    stats["ml_runtime_seconds"] = ml["runtime_seconds"]
    stats["ml_training"] = ml["training"]
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New immutable result directory")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    code_files = [
        Path(__file__),
        ROOT / "experiments/requirements.txt",
        *sorted((ROOT / "backend/src/replenishment/calculation").glob("*.py")),
        ROOT / "backend/src/replenishment/intake/adapters/normalization.py",
        ROOT / "backend/src/replenishment/intake/adapters/xlsx.py",
        ROOT / "backend/tests/evaluation/cases.py",
        ROOT / "backend/tests/evaluation/contracts.py",
    ]
    code_snapshot = {str(path.relative_to(ROOT)): path.read_bytes() for path in code_files}
    batch = read_batch()
    development = compare(batch["series"], [f"2025-{m:02}-01" for m in range(6, 10)], "development")
    champion = development["selected_model"]
    gate = promotion_gate(development["metrics"][champion], development["metrics"]["lightgbm"])
    selected = "lightgbm" if gate["promote"] else champion
    print(json.dumps({"phase": "development", "champion": champion, "gate": gate}), flush=True)
    retrospective = compare(batch["series"], [f"2026-{m:02}-01" for m in range(1, 6)], "retrospective")
    report = {
        "protocol": "monthly-forecast-evaluation-v2",
        "series_count": len(batch["series"]),
        "source_selection": batch["source_selection"],
        "configuration": MODEL_CONFIG,
        "python": platform.python_version(),
        "promotion_gate": gate,
        "selection_frozen": selected,
        "retrospective_is_previously_inspected": True,
        "llm_cost_usd": "0",
        "development": development,
        "retrospective": retrospective,
        "code_sha256": {path: hashlib.sha256(content).hexdigest() for path, content in code_snapshot.items()},
        "reproduction_command": (
            "experiments/.venv/bin/python scripts/backtest_monthly_lightgbm.py --output <new-directory>"
        ),
    }
    args.output.mkdir(parents=True)
    for path, content in code_snapshot.items():
        target = args.output / "code" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    for phase in ("development", "retrospective"):
        with gzip.open(args.output / f"{phase}-targets.jsonl.gz", "wt", encoding="utf-8") as output:
            for row in report[phase].pop("rows"):
                output.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        excluded = report[phase].pop("excluded")
        report[phase]["excluded_count"] = len(excluded)
        report[phase]["excluded_examples"] = excluded[:20]
    (args.output / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    )
    print(json.dumps({"selected": selected, "output": str(args.output), "gate": gate}))


if __name__ == "__main__":
    main()
