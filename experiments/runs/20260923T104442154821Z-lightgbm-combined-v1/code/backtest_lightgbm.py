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


def bulk_features(keys, decisions, origin):
    """Document frequency/size signals from decisions available strictly before origin."""
    indexes = {key: i for i, key in enumerate(keys)}
    counts = np.zeros((len(keys), 84))
    flagged = np.zeros_like(counts)
    excess = np.zeros_like(counts)
    for decision in decisions:
        order = decision.order
        age = (origin - order.day).days
        if age <= 0:
            raise ValueError("Bulk features cannot include current/future orders")
        if age > 84:
            continue
        i = indexes[(order.sku, order.unit)]
        counts[i, age - 1] += 1
        if decision.excluded_quantity > 0:
            flagged[i, age - 1] += 1
            excess[i, age - 1] += float(decision.excluded_quantity)
    columns, names = [], []
    for window in (7, 28, 56, 84):
        total = counts[:, :window].sum(axis=1)
        events = flagged[:, :window].sum(axis=1)
        removed = excess[:, :window].sum(axis=1)
        names += [f"bulk_orders_{window}", f"bulk_order_fraction_{window}", f"bulk_mean_excess_{window}"]
        columns += [events, events / np.maximum(total, 1), removed / np.maximum(events, 1)]
    names.append("days_since_bulk_capped84")
    columns.append(np.where(flagged.any(axis=1), np.argmax(flagged > 0, axis=1) + 1, 84))
    return np.column_stack(columns).astype(np.float32), names


def combined_features(history, cleaned, sku_ids, origin, signals, signal_names):
    """Keep every raw feature; append cleaned demand features and bulk-order signals."""
    if history.shape != cleaned.shape or not np.isfinite(cleaned).all() or (cleaned < 0).any():
        raise ValueError("Expected aligned finite nonnegative cleaned history")
    if np.any(cleaned > history + 1e-8):
        raise ValueError("Cleaning cannot add sales")
    raw, names = features(history, sku_ids, origin)
    regular, clean_names = features(cleaned, sku_ids, origin)
    # Identity/calendar/occurrence are unchanged by positive median replacement.
    keep = [i for i, name in enumerate(clean_names)
            if name.startswith(("mean_", "week_lag_"))
            or name in ("max_56", "std_56", "positive_size_56", "recent_ratio")]
    result = np.column_stack([raw, regular[:, keep], signals])
    return result, names + [f"clean_{clean_names[i]}" for i in keep] + signal_names


def combined_self_check():
    from decimal import Decimal
    from types import SimpleNamespace

    origin = date(2025, 4, 11)
    raw = np.full((2, 100), 10.)
    cleaned = raw.copy()
    raw[0, -1] += 1000
    keys = [("a", "pcs"), ("b", "pcs")]
    decisions = [SimpleNamespace(order=SimpleNamespace(sku="a", unit="pcs", day=origin - timedelta(days=1)),
                                 excluded_quantity=Decimal(1000)),
                 SimpleNamespace(order=SimpleNamespace(sku="a", unit="pcs", day=origin - timedelta(days=2)),
                                 excluded_quantity=Decimal(0))]
    signals, signal_names = bulk_features(keys, decisions, origin)
    output, names = combined_features(raw, cleaned, np.arange(2), origin, signals, signal_names)
    original, original_names = features(raw, np.arange(2), origin)
    assert np.array_equal(output[:, :len(original_names)], original)
    assert len(names) == len(set(names)) == output.shape[1] == 59
    assert output[0, names.index("clean_mean_7")] == 10
    assert output[0, names.index("bulk_orders_7")] == 1
    assert output[0, names.index("bulk_order_fraction_7")] == 0.5
    assert output[0, names.index("bulk_mean_excess_7")] == 1000
    assert output[0, names.index("days_since_bulk_capped84")] == 1
    assert output[1, names.index("days_since_bulk_capped84")] == 84
    try:
        bulk_features(keys, decisions, origin - timedelta(days=1))
    except ValueError:
        pass
    else:
        raise AssertionError("Future evidence must be rejected")


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
    parser.add_argument("--cleaning", action="store_true", help="Paired raw/clean Tweedie; unchanged training and test labels")
    parser.add_argument("--combined", action="store_true", help="Raw plus cleaned history and bulk signals")
    args = parser.parse_args()
    if sum((args.ablation, args.cleaning, args.combined)) > 1:
        parser.error("Choose only one of ablation, cleaning, or combined")
    needs_cleaning = args.cleaning or args.combined
    out = base.ROOT / "artifacts/lightgbm-ablation" if args.ablation else OUT
    candidates = {f"tweedie_{v}": CANDIDATES["lgbm_tweedie"] for v in
                  ("full", "no_sku", "no_calendar", "no_week_lags")} if args.ablation else CANDIDATES
    variants = {m: m.removeprefix("tweedie_") if args.ablation else "full" for m in candidates}
    if needs_cleaning:
        import backtest_cleaning as cleaning
        out = base.ROOT / "artifacts/lightgbm-cleaning"
        candidates = {m: CANDIDATES["lgbm_tweedie"] for m in ("tweedie_raw", "tweedie_clean")}
        variants = {m: "full" for m in candidates}
    if args.combined:
        out = base.ROOT / "artifacts/lightgbm-combined"
        candidates = {m: CANDIDATES["lgbm_tweedie"] for m in ("tweedie_raw", "tweedie_combined")}
        variants = {m: "full" for m in candidates}
        combined_self_check()
    started = perf_counter()
    self_check()
    script_paths = [Path(__file__), Path(base.__file__), Path(__file__).with_name("backtest_intermittent.py")]
    if needs_cleaning:
        script_paths += [Path(cleaning.__file__), cleaning.POLICY_PATH]
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
    candidate_names = {}
    for folder in sorted((base.ROOT / "docs/data").iterdir()):
        source_rows = [] if needs_cleaning else None
        keys, _, matrix, _, metadata = base.load_supplier(folder, source_rows)
        expected = next(s for s in previous["source_files"] if s["supplier"] == folder.name)
        assert metadata["sha256"] == expected["sha256"] and metadata["warehouses"] == ["Алматы"]
        sources.append({"supplier": folder.name, **metadata})
        cleaned, bulk = {}, {}
        if needs_cleaning:
            orders, _ = cleaning.prepare_orders(folder, source_rows)
            cleaner = cleaning.CleaningHistory(orders, keys)
            for offset in all_offsets:
                cutoff = base.START + timedelta(days=offset)
                cleaned[offset], decisions = cleaner.at(cutoff)
                if args.combined:
                    bulk[offset], bulk_names = bulk_features(keys, decisions, cutoff)
            # Verify cached cleaning against full prefix-only decisions at a training and test origin.
            if args.combined:
                for offset in (all_offsets[0], offsets[-1]):
                    cutoff = base.START + timedelta(days=offset)
                    direct = cleaning.clean_orders(orders, as_of=cutoff)
                    assert np.array_equal(cleaned[offset], cleaning.matrix_from_decisions(keys, direct, offset))
                    assert np.array_equal(bulk[offset], bulk_features(keys, direct, cutoff)[0])
            print(json.dumps({"supplier": folder.name, "cleaned_origins": len(cleaned)}), flush=True)
        for unit in sorted({k[1] for k in keys}):
            indexes = [i for i, k in enumerate(keys) if k[1] == unit]
            local_keys = [keys[i] for i in indexes]
            y = matrix[indexes]
            first_sale = np.argmax(y > 0, axis=1)
            blocks, clean_features = {}, {}
            for offset in all_offsets:
                eligible = np.flatnonzero(first_sale <= offset - 90)
                if not len(eligible):
                    continue
                history = y[eligible, :offset]
                xf, names = features(history, eligible, base.START + timedelta(days=offset))
                segments = (history[:, -56:].reshape(len(history), 8, 7).sum(axis=2) > 0).sum(axis=1)
                blocks[offset] = (eligible, xf, segments)
                if needs_cleaning:
                    clean_history = cleaned[offset][indexes][eligible]
                    if args.combined:
                        clean_features[offset], extra_names = combined_features(
                            history, clean_history, eligible, base.START + timedelta(days=offset),
                            bulk[offset][indexes][eligible], bulk_names)
                    else:
                        clean_features[offset], extra_names = features(
                            clean_history, eligible, base.START + timedelta(days=offset))
            for horizon in (7, 28):
                ts = [t for t in train_offsets if t in blocks and t + horizon <= max(offsets)]
                xtrain = np.concatenate([blocks[t][1] for t in ts])
                if needs_cleaning:
                    xtrain_clean = np.concatenate([clean_features[t] for t in ts])
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
                        enhanced = model_id in ("tweedie_clean", "tweedie_combined")
                        available_names = extra_names if enhanced else names
                        columns = feature_columns(available_names, variants[model_id])
                        model_names = [available_names[i] for i in columns]
                        candidate_names[model_id] = model_names
                        model_train = xtrain_clean if enhanced else xtrain
                        model_predict = clean_features[offset] if enhanced else xp
                        dataset = lgb.Dataset(model_train[mask][:, columns], label=ytrain[mask], feature_name=model_names,
                                              categorical_feature=[n for n in model_names if n == "sku_id"])
                        model = lgb.train({**PARAMS, **objective}, dataset, num_boost_round=ROUNDS)
                        forecasts[model_id] = np.maximum(model.predict(model_predict[:, columns], num_threads=2), 0)
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
    forecast_selections = {}
    if args.combined:
        # Baseline wins ties; no model choice is based on the retrospective period.
        forecast_selections = {
            k: min(["baseline_selected", *candidates], key=lambda m: score(v, m)["wape_pct"])
            for k, v in development.items()
        }
        for row in rows:
            row["forecast_selected"] = row[forecast_selections[
                (row["supplier"], row["unit"], row["horizon"])]]
        models.append("forecast_selected")
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
    summary = {"protocol": ("Combined v1; raw plus clean history and bulk signals; raw labels" if args.combined else
                            "Issue #3; paired Tweedie raw/clean features; raw labels" if args.cleaning else
                            "Track B2; fixed Tweedie feature ablation" if args.ablation else
                            "Track B v1; direct horizon totals; fixed two-objective grid"),
               "source_files": sources, "script_sha256": hashes,
               "baseline_results_sha256": hashlib.sha256((base.OUT / "results.json").read_bytes()).hexdigest(),
               "parameters": PARAMS, "candidates": candidates, "num_boost_round": ROUNDS,
               "candidate_features": candidate_names,
               "selections": [{"supplier": k[0], "unit": k[1], "horizon": k[2], "model": v} for k, v in selections.items()],
               "forecast_selections": [{"supplier": k[0], "unit": k[1], "horizon": k[2], "model": v}
                                       for k, v in forecast_selections.items()],
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
