"""Track B: direct horizon-total LightGBM, fixed settings, shared benchmark keys."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter

import lightgbm as lgb
import numpy as np
import openpyxl

import backtest_demand as base
from backtest_intermittent import score

OUT = base.ROOT / "artifacts/lightgbm-experiment"
PARAMS = dict(learning_rate=0.05, num_leaves=15, min_data_in_leaf=50,
              lambda_l2=1.0, max_bin=63, num_threads=2, verbosity=-1,
              seed=20260923, deterministic=True, force_col_wise=True)
CANDIDATES = {"lgbm_l2": {"objective": "regression"},
              "lgbm_tweedie": {"objective": "tweedie", "tweedie_variance_power": 1.5}}
ROUNDS = 150


def feature_columns(names, variant):
    excluded = {"no_sku": {"sku_id"},
                "no_calendar": {"month_sin", "month_cos", "weekday", "month_day"},
                "no_week_lags": {f"week_lag_{i}" for i in range(1, 9)},
                "full": set()}[variant]
    return [i for i, name in enumerate(names) if name not in excluded]


def features(history, sku_ids, origin):
    """No target or future data is accepted. SKU codes are categorical, not numeric scale."""
    n = len(history)
    positive = history > 0
    first = np.argmax(positive, axis=1)
    names = ["sku_id", "age", "days_since_sale", "month_sin", "month_cos", "weekday", "month_day"]
    columns = [sku_ids, history.shape[1] - first,
               np.where(positive.any(axis=1), np.argmax(positive[:, ::-1], axis=1), history.shape[1]),
               np.full(n, np.sin(2 * np.pi * origin.month / 12)),
               np.full(n, np.cos(2 * np.pi * origin.month / 12)),
               np.full(n, origin.weekday()), np.full(n, origin.day)]
    for window in (7, 14, 28, 56, 84):
        x = history[:, -window:]
        names += [f"mean_{window}", f"active_fraction_{window}"]
        columns += [x.mean(axis=1), (x > 0).mean(axis=1)]
    for lag in range(8):
        end = history.shape[1] - lag * 7
        names.append(f"week_lag_{lag + 1}")
        columns.append(history[:, end - 7:end].sum(axis=1))
    x = history[:, -56:]
    names += ["max_56", "std_56", "positive_size_56", "recent_ratio"]
    columns += [x.max(axis=1), x.std(axis=1), x.sum(axis=1) / np.maximum((x > 0).sum(axis=1), 1),
                history[:, -28:].sum(axis=1) / (1 + history[:, -56:-28].sum(axis=1))]
    return np.column_stack(columns).astype(np.float32), names


def self_check():
    x = np.zeros((2, 100))
    x[0, 0] = 10
    x[0, -1] = 5
    f, names = features(x, np.arange(2), date(2025, 4, 11))
    assert f[0, names.index("days_since_sale")] == 0
    assert f[1, names.index("days_since_sale")] == 100
    assert np.isclose(f[0, names.index("mean_7")], 5 / 7)
    expanded = np.concatenate([x, np.full((2, 28), 999999)], axis=1)
    assert np.array_equal(f, features(expanded[:, :100], np.arange(2), date(2025, 4, 11))[0])
    # Label availability is exclusive of the forecast origin.
    origins = np.array([90, 100, 110])
    assert np.array_equal(origins[origins + 28 <= 128], [90, 100])
    for variant, removed in (("full", 0), ("no_sku", 1), ("no_calendar", 4), ("no_week_lags", 8)):
        indexes = feature_columns(names, variant)
        assert len(indexes) == len(names) - removed
        assert indexes == sorted(set(indexes))
    assert "sku_id" not in [names[i] for i in feature_columns(names, "no_sku")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ablation", action="store_true", help="Fixed Tweedie feature ablations; separate output directory")
    args = parser.parse_args()
    out = base.ROOT / "artifacts/lightgbm-ablation" if args.ablation else OUT
    candidates = {f"tweedie_{v}": CANDIDATES["lgbm_tweedie"] for v in
                  ("full", "no_sku", "no_calendar", "no_week_lags")} if args.ablation else CANDIDATES
    variants = {m: m.removeprefix("tweedie_") if args.ablation else "full" for m in candidates}
    started = perf_counter()
    self_check()
    script_paths = [Path(__file__), Path(base.__file__), Path(__file__).with_name("backtest_intermittent.py")]
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in script_paths}
    previous = json.loads((base.OUT / "results.json").read_text(encoding="utf-8"))
    with (base.OUT / "predictions.csv").open(encoding="utf-8-sig", newline="") as f:
        saved = list(csv.DictReader(f))
    identity = lambda r: (r["supplier"], r["sku"], r["unit"], r["origin"], int(r["horizon"]))
    baseline = {identity(r): r for r in saved}
    origins = [date.fromisoformat(s) for s in previous["origin_dates"]]
    offsets = [(o - base.START).days for o in origins]
    # Weekly examples plus historical month-start examples; evaluation keys stay unchanged.
    train_offsets = sorted(set(range(90, max(offsets), 7)) | {d for d in offsets if d < max(offsets)})
    all_offsets = sorted(set(train_offsets) | set(offsets))
    rows, sources, training, importance = [], [], [], []
    for folder in sorted((base.ROOT / "docs/data").iterdir()):
        keys, _, matrix, _, metadata = base.load_supplier(folder)
        expected = next(s for s in previous["source_files"] if s["supplier"] == folder.name)
        assert metadata["sha256"] == expected["sha256"] and metadata["warehouses"] == ["Алматы"]
        sources.append({"supplier": folder.name, **metadata})
        for unit in sorted({k[1] for k in keys}):
            indexes = [i for i, k in enumerate(keys) if k[1] == unit]
            local_keys = [keys[i] for i in indexes]
            y = matrix[indexes]
            first_sale = np.argmax(y > 0, axis=1)
            blocks = {}
            for offset in all_offsets:
                eligible = np.flatnonzero(first_sale <= offset - 90)
                if not len(eligible):
                    continue
                history = y[eligible, :offset]
                xf, names = features(history, eligible, base.START + timedelta(days=offset))
                segments = (history[:, -56:].reshape(len(history), 8, 7).sum(axis=2) > 0).sum(axis=1)
                blocks[offset] = (eligible, xf, segments)
            for horizon in (7, 28):
                ts = [t for t in train_offsets if t in blocks and t + horizon <= max(offsets)]
                xtrain = np.concatenate([blocks[t][1] for t in ts])
                ytrain = np.concatenate([y[blocks[t][0], t:t + horizon].sum(axis=1) for t in ts])
                label_ends = np.concatenate([np.full(len(blocks[t][0]), t + horizon) for t in ts])
                for origin, offset in zip(origins, offsets):
                    eligible, xp, segments = blocks[offset]
                    mask = label_ends <= offset
                    assert mask.any() and label_ends[mask].max() <= offset
                    observed = y[eligible, offset:offset + horizon].sum(axis=1)
                    forecasts = {}
                    for model_id, objective in candidates.items():
                        tick = perf_counter()
                        columns = feature_columns(names, variants[model_id])
                        model_names = [names[i] for i in columns]
                        dataset = lgb.Dataset(xtrain[mask][:, columns], label=ytrain[mask], feature_name=model_names,
                                              categorical_feature=[n for n in model_names if n == "sku_id"])
                        model = lgb.train({**PARAMS, **objective}, dataset, num_boost_round=ROUNDS)
                        forecasts[model_id] = np.maximum(model.predict(xp[:, columns], num_threads=2), 0)
                        assert np.isfinite(forecasts[model_id]).all()
                        training.append({"supplier": folder.name, "unit": unit, "horizon": horizon,
                                         "origin": origin.isoformat(), "model": model_id, "train_rows": int(mask.sum()),
                                         "last_label_end_exclusive": (base.START + timedelta(days=int(label_ends[mask].max()))).isoformat(),
                                         "seconds": perf_counter() - tick})
                        if origin == origins[-1]:
                            importance.extend({"supplier": folder.name, "unit": unit, "horizon": horizon,
                                               "model": model_id, "feature": name, "gain": float(gain)}
                                              for name, gain in zip(model_names, model.feature_importance("gain")))
                    for j, i in enumerate(eligible):
                        key = (folder.name, local_keys[i][0], unit, origin.isoformat(), horizon)
                        old = baseline[key]
                        assert np.isclose(observed[j], float(old["actual"]), rtol=1e-10, atol=1e-8)
                        segment = "regular" if segments[j] >= 4 else "intermittent"
                        assert segment == old["segment"]
                        rows.append({"supplier": key[0], "sku": key[1], "unit": unit, "origin": key[3],
                                     "horizon": horizon, "phase": "development_2025" if origin.year == 2025 else "retrospective_2026",
                                     "segment": segment, "actual": float(observed[j]),
                                     "baseline_selected": float(old["selected_2025"]),
                                     **{m: float(v[j]) for m, v in forecasts.items()}})
                    print(json.dumps({"supplier": folder.name, "unit": unit, "horizon": horizon,
                                      "origin": origin.isoformat(), "train_rows": int(mask.sum())}, ensure_ascii=True), flush=True)
    assert len(rows) == len(baseline) and {identity(r) for r in rows} == set(baseline)
    development = defaultdict(list)
    for row in rows:
        if row["phase"] == "development_2025":
            development[(row["supplier"], row["unit"], row["horizon"])].append(row)
    selections = {k: min(candidates, key=lambda m: score(v, m)["wape_pct"]) for k, v in development.items()}
    for row in rows:
        row["lgbm_selected"] = row[selections[(row["supplier"], row["unit"], row["horizon"])]]
    models = ["baseline_selected", *candidates, "lgbm_selected"]
    groups, monthly = defaultdict(list), defaultdict(list)
    for row in rows:
        key = (row["phase"], row["supplier"], row["unit"], row["horizon"])
        for segment in ("all", row["segment"]):
            groups[(*key, segment)].append(row)
        monthly[(row["origin"], row["supplier"], row["unit"], row["horizon"])].append(row)
    metrics = [{"phase": k[0], "supplier": k[1], "unit": k[2], "horizon": k[3], "segment": k[4],
                "model": m, **score(v, m)} for k, v in groups.items() for m in models]
    monthly_metrics = [{"origin": k[0], "supplier": k[1], "unit": k[2], "horizon": k[3],
                        "model": m, **score(v, m)} for k, v in monthly.items() for m in models]
    out.mkdir(parents=True, exist_ok=True)
    base.write_csv(out / "candidate_predictions.csv", rows)
    base.write_csv(out / "metrics.csv", metrics)
    base.write_csv(out / "monthly_metrics.csv", monthly_metrics)
    base.write_csv(out / "training.csv", training)
    base.write_csv(out / "feature_importance.csv", importance)
    with (out / "predictions.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["model_id", "supplier", "sku", "unit", "origin", "horizon_days", "forecast", "actual"])
        writer.writeheader()
        for row in rows:
            for model_id in models:
                writer.writerow({"model_id": model_id, **{k: row[k] for k in ("supplier", "sku", "unit", "origin", "actual")},
                                 "horizon_days": row["horizon"], "forecast": row[model_id]})
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in script_paths}
    summary = {"protocol": "Track B2; fixed Tweedie feature ablation" if args.ablation else "Track B v1; direct horizon totals; fixed two-objective grid",
               "source_files": sources, "script_sha256": hashes,
               "baseline_results_sha256": hashlib.sha256((base.OUT / "results.json").read_bytes()).hexdigest(),
               "parameters": PARAMS, "candidates": candidates, "num_boost_round": ROUNDS,
               "candidate_features": {m: [names[i] for i in feature_columns(names, v)] for m, v in variants.items()},
               "selections": [{"supplier": k[0], "unit": k[1], "horizon": k[2], "model": v} for k, v in selections.items()],
               "feature_names": names, "rows": len(rows), "elapsed_seconds": perf_counter() - started,
               "fit_predict_seconds": sum(t["seconds"] for t in training),
               "environment": {"python": sys.version, "numpy": np.__version__, "openpyxl": openpyxl.__version__,
                               "lightgbm": lgb.__version__, "platform": platform.platform(), "processor": platform.processor()},
               "metrics": metrics, "comparison_is_retrospective": True,
               "source_and_baseline_reconciliation": "exact key sets; all target and segment values checked"}
    (out / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "seconds": summary["elapsed_seconds"], "selections": summary["selections"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
