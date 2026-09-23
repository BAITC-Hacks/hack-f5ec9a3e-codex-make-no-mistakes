"""Track C: NumPy Croston-SBA/TSB, using the existing demand benchmark loader.

Run: python scripts/backtest_intermittent.py
Dependencies: numpy, openpyxl (same as backtest_demand.py).
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from time import perf_counter

import numpy as np
import openpyxl

import backtest_demand as base

OUT = base.ROOT / "artifacts/intermittent-experiment"
# Fixed before looking at Track C's 2026 comparison. No post-result tuning.
CONFIGS = [("sba", a, 0.0) for a in (0.05, 0.1, 0.2)] + [
    ("tsb", a, p) for a in (0.05, 0.1, 0.2) for p in (0.01, 0.05, 0.1, 0.2)
]
IDS = [f"{family}_a{a:g}_p{p:g}" for family, a, p in CONFIGS]
BASELINES = base.SHORT_MODELS


def rates_at_origins(matrix, offsets):
    """Daily rates immediately before each origin; all states use only the past.

    SBA: smooth positive sizes and arrival intervals, multiply ratio by 1-alpha/2.
    Initialize size with first positive quantity, interval with its 1-based day.
    TSB: same size state, but smooth daily occurrence from day-1's indicator.
    Zero-history forecasts are zero. Trailing zeros decay TSB probability only.
    """
    if matrix.ndim != 2 or not np.isfinite(matrix).all() or (matrix < 0).any():
        raise ValueError("Expected finite nonnegative daily sales matrix")
    if not offsets or min(offsets) < 1 or max(offsets) > matrix.shape[1]:
        raise ValueError("Origins must have history within the matrix")
    alpha = np.array([c[1] for c in CONFIGS])[:, None]
    beta = np.array([c[2] for c in CONFIGS])[:, None]
    is_sba = np.array([c[0] == "sba" for c in CONFIGS])[:, None]
    size = np.zeros((len(CONFIGS), len(matrix)))
    interval = np.ones_like(size)
    probability = np.zeros_like(size)
    seen = np.zeros(len(matrix), dtype=bool)
    last = np.full(len(matrix), -1)
    snapshots = {}
    for t in range(max(offsets)):
        y = matrix[:, t]
        positive = y > 0
        first = positive & ~seen
        repeat = positive & seen
        size[:, first] = y[first]
        interval[:, first] = t + 1
        size[:, repeat] += alpha * (y[repeat] - size[:, repeat])
        interval[:, repeat] += alpha * (t - last[repeat] - interval[:, repeat])
        if t == 0:
            probability[:] = positive
        else:
            probability += beta * (positive - probability)
        seen |= positive
        last[positive] = t
        if t + 1 in offsets:
            snapshots[t + 1] = np.where(
                is_sba, (1 - alpha / 2) * size / interval, size * probability
            )
    return snapshots


def self_check():
    # Hand-computed irregular sequence checks initialization and both recurrences.
    a = IDS.index("sba_a0.1_p0")
    b = IDS.index("tsb_a0.1_p0.2")
    x = np.array([[0., 10., 0., 20., 0.]])
    r = rates_at_origins(x, [4, 5])
    assert np.isclose(r[4][a, 0], 0.95 * 11 / 2)
    assert np.isclose(r[4][b, 0], 11 * 0.328)
    assert r[5][a, 0] == r[4][a, 0]
    assert np.isclose(r[5][b, 0], r[4][b, 0] * 0.8)
    assert not rates_at_origins(np.zeros((2, 100)), [100])[100].any()
    steady = rates_at_origins(np.full((1, 100), 10.), [100])[100]
    assert np.isclose(steady[a, 0], 9.5) and np.isclose(steady[b, 0], 10)
    extended = np.concatenate([x, np.full((1, 20), 999999.)], axis=1)
    assert np.array_equal(r[5], rates_at_origins(extended, [5])[5])
    # Batching must not alter a series' result.
    batched = rates_at_origins(np.vstack([x, x * 2]), [5])[5]
    assert np.allclose(batched[:, 0], r[5][:, 0])
    assert np.allclose(batched[:, 1], 2 * r[5][:, 0])


def score(rows, model):
    result = base.score(rows, model)
    result["mae"] = float(np.mean([abs(r[model] - r["actual"]) for r in rows]))
    return result


def main():
    started = perf_counter()
    self_check()
    base.self_check()
    script_paths = [Path(__file__), Path(base.__file__)]
    script_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in script_paths}
    origins = [date(2025, m, 1) for m in range(7, 13)] + [date(2026, m, 1) for m in range(1, 9)]
    offsets = [(o - base.START).days for o in origins]
    rows, sources, timings = [], [], []
    previous = json.loads((base.OUT / "results.json").read_text(encoding="utf-8"))
    expected_sources = {s["supplier"]: s["sha256"] for s in previous["source_files"]}
    for folder in sorted((base.ROOT / "docs/data").iterdir()):
        start = perf_counter()
        keys, _, matrix, _, metadata = base.load_supplier(folder)
        assert metadata["warehouses"] == ["Алматы"]
        assert metadata["sha256"] == expected_sources[folder.name]
        sources.append({"supplier": folder.name, **metadata})
        load_seconds = perf_counter() - start
        start = perf_counter()
        snapshots = rates_at_origins(matrix, offsets)
        model_seconds = perf_counter() - start
        first_sale = np.argmax(matrix > 0, axis=1)
        for origin, offset in zip(origins, offsets):
            eligible = first_sale <= offset - 90
            indexes = np.flatnonzero(eligible)
            history = matrix[eligible, :offset]
            active = (history[:, -56:].reshape(len(history), 8, 7).sum(axis=2) > 0).sum(axis=1)
            for horizon in (7, 28):
                forecasts = base.forecast(history, horizon)
                actual = matrix[eligible, offset:offset + horizon].sum(axis=1)
                for j, index in enumerate(indexes):
                    sku, unit = keys[index]
                    rows.append({"supplier": folder.name, "sku": sku, "unit": unit,
                                 "origin": origin.isoformat(), "horizon": horizon,
                                 "phase": "development_2025" if origin.year == 2025 else "retrospective_2026",
                                 "segment": "regular" if active[j] >= 4 else "intermittent",
                                 "actual": float(actual[j]),
                                 **{m: float(forecasts[m][j]) for m in BASELINES},
                                 **{m: float(snapshots[offset][k, index] * horizon) for k, m in enumerate(IDS)}})
        timings.append({"supplier": folder.name, "load_seconds": load_seconds,
                        "all_15_models_all_origins_seconds": model_seconds})
    # Independently reconstructed keys/actuals/baselines must match the existing experiment.
    identity = lambda r: (r["supplier"], r["sku"], r["unit"], r["origin"], int(r["horizon"]))
    lookup = {identity(r): r for r in rows}
    assert len(lookup) == len(rows) == previous["forecast_rows"]
    with (base.OUT / "predictions.csv").open(encoding="utf-8-sig", newline="") as f:
        saved = list(csv.DictReader(f))
    assert {identity(r) for r in saved} == set(lookup)
    for old in saved:
        new = lookup[identity(old)]
        for m in ["actual", *BASELINES]:
            assert np.isclose(new[m], float(old[m]), rtol=1e-10, atol=1e-8), (identity(old), m)

    development = defaultdict(list)
    for row in rows:
        if row["phase"] == "development_2025":
            development[(row["supplier"], row["unit"], row["horizon"])].append(row)
    selections, grid_metrics = {}, []
    families = {"baseline_selected": BASELINES,
                "sba_selected": [m for m in IDS if m.startswith("sba")],
                "tsb_selected": [m for m in IDS if m.startswith("tsb")]}
    for key, subset in sorted(development.items()):
        scores = {m: score(subset, m) for m in [*BASELINES, *IDS]}
        selections[key] = {family: min(models, key=lambda m: scores[m]["wape_pct"]
                                      if scores[m]["wape_pct"] is not None else float("inf"))
                           for family, models in families.items()}
        for model, values in scores.items():
            grid_metrics.append({"supplier": key[0], "unit": key[1], "horizon": key[2],
                                 "model": model, **values})
    for row in rows:
        for family, model in selections[(row["supplier"], row["unit"], row["horizon"])].items():
            row[family] = row[model]
    models = [*BASELINES, *families]
    grouped, monthly = defaultdict(list), defaultdict(list)
    for row in rows:
        key = (row["phase"], row["supplier"], row["unit"], row["horizon"])
        for segment in ("all", row["segment"]):
            grouped[(*key, segment)].append(row)
        monthly[(row["origin"], row["supplier"], row["unit"], row["horizon"])].append(row)
    metrics = [{"phase": k[0], "supplier": k[1], "unit": k[2], "horizon": k[3],
                "segment": k[4], "model": m, **score(v, m)}
               for k, v in grouped.items() for m in models]
    monthly_metrics = [{"origin": k[0], "supplier": k[1], "unit": k[2], "horizon": k[3],
                        "model": m, **score(v, m)} for k, v in monthly.items() for m in models]
    OUT.mkdir(parents=True, exist_ok=True)
    base.write_csv(OUT / "grid_development.csv", grid_metrics)
    base.write_csv(OUT / "metrics.csv", metrics)
    base.write_csv(OUT / "monthly_metrics.csv", monthly_metrics)
    base.write_csv(OUT / "candidate_predictions.csv", rows)
    # Common long-format interchange, only the development-selected family members.
    with (OUT / "predictions.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["model_id", "supplier", "sku", "unit", "origin",
                                              "horizon_days", "forecast", "actual"])
        writer.writeheader()
        for row in rows:
            for family in families:
                assert np.isfinite(row[family]) and row[family] >= 0
                writer.writerow({"model_id": family, **{k: row[k] for k in ("supplier", "sku", "unit", "origin", "actual")},
                                 "horizon_days": row["horizon"], "forecast": row[family]})
    assert script_hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in script_paths}
    summary = {"protocol": "Track C v1; daily states; 2025-only all-cohort WAPE selection",
               "source_files": sources, "script_sha256": script_hashes,
               "baseline_results_sha256": hashlib.sha256((base.OUT / "results.json").read_bytes()).hexdigest(),
               "configs": [{"model": m, "family": c[0], "alpha_size": c[1], "alpha_probability": c[2]}
                           for m, c in zip(IDS, CONFIGS)],
               "selections": [{"supplier": k[0], "unit": k[1], "horizon": k[2], **v} for k, v in selections.items()],
               "rows": len(rows), "source_and_baseline_reconciliation": "passed for every key and value",
               "timings": timings, "elapsed_seconds": perf_counter() - started,
               "environment": {"python": sys.version, "numpy": np.__version__, "openpyxl": openpyxl.__version__,
                               "platform": platform.platform(), "processor": platform.processor()},
               "metrics": metrics, "randomness": "none", "comparison_is_retrospective": True}
    (OUT / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "seconds": summary["elapsed_seconds"],
                      "selections": summary["selections"], "timings": timings}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
