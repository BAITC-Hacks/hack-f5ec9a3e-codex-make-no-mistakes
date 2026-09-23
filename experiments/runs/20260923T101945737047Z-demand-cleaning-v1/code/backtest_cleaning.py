"""Issue #3: document-level cleaning and paired forecasts on unchanged benchmark targets."""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import perf_counter

import numpy as np
import openpyxl

import backtest_demand as base
from backtest_intermittent import score

# Reuse the application's pure domain policy in the separate Python 3.10 research environment.
sys.path.insert(0, str(base.ROOT / "backend/src"))
from replenishment.demand.cleaning import (  # noqa: E402
    POLICY_VERSION, CleaningDecision, Order, clean_orders, movement_reason,
)
import replenishment.demand.cleaning as policy  # noqa: E402

OUT = base.ROOT / "artifacts/demand-cleaning"
POLICY_PATH = Path(policy.__file__)


def prepare_orders(folder, source_rows):
    """Retain every movement's provenance; aggregate accepted lines by document identity."""
    groups, ledger = {}, []
    for row_number, row in source_rows:
        stamp, number, document, sku, _, unit, warehouse, raw = row
        try:
            quantity = None if raw is None else Decimal(str(raw))
        except InvalidOperation:
            quantity = Decimal("NaN")
        try:
            day = stamp.date() if isinstance(stamp, datetime) else datetime.strptime(str(stamp), "%d.%m.%Y %H:%M:%S").date()
        except (ValueError, TypeError):
            day = None
        reason = movement_reason(str(document), quantity)
        if day is None or any(v is None or not str(v).strip() for v in (number, document, sku, unit, warehouse)):
            reason = "invalid_identity_or_date"
        in_period = day is not None and base.START <= day <= base.END
        ledger.append({"supplier": folder.name, "source_row": row_number, "date": day,
                       "document_number": number, "document": document, "sku": sku,
                       "unit": unit, "warehouse": warehouse, "original_quantity": raw,
                       "movement_reason": reason, "in_experiment_period": in_period})
        if reason != "positive_outgoing" or not in_period:
            continue
        key = (str(sku), str(unit), str(warehouse), day, str(number), str(document))
        if key not in groups:
            groups[key] = [Decimal(0), []]
        groups[key][0] += quantity
        groups[key][1].append(row_number)
    orders = [Order(folder.name, sku, unit, warehouse, day, number + " | " + document, qty, tuple(rows))
              for (sku, unit, warehouse, day, number, document), (qty, rows) in groups.items()]
    return orders, ledger


def matrix_from_decisions(keys, decisions, days):
    matrix = np.zeros((len(keys), days))
    indexes = {key: i for i, key in enumerate(keys)}
    for decision in decisions:
        order = decision.order
        matrix[indexes[(order.sku, order.unit)], (order.day - base.START).days] += float(decision.regular_quantity)
    return matrix


class CleaningHistory:
    """Reuse fixed past thresholds, recomputing the only revisable seven-day tail.

    Decisions at least seven days old have their full persistence neighborhood
    before the cutoff. Tail decisions need 56 earlier days for their thresholds.
    This is equivalent to clean_orders(prefix, as_of), checked by the runner.
    """

    def __init__(self, orders, keys):
        self.orders, self.keys = orders, keys
        self.full = clean_orders(orders, as_of=base.END + timedelta(days=1))

    def at(self, as_of):
        boundary = as_of - timedelta(days=7)
        old = [d for d in self.full if d.order.day < boundary]
        tail_orders = [o for o in self.orders if boundary - timedelta(days=56) <= o.day < as_of]
        tail = [d for d in clean_orders(tail_orders, as_of=as_of) if d.order.day >= boundary]
        decisions = old + tail
        return matrix_from_decisions(self.keys, decisions, (as_of - base.START).days), decisions


def decision_row(decision):
    order = decision.order
    return {"supplier": order.supplier, "sku": order.sku, "unit": order.unit,
            "warehouse": order.warehouse, "day": order.day, "document": order.document,
            "source_rows": ";".join(map(str, order.source_rows)), "original_quantity": order.quantity,
            "regular_quantity": decision.regular_quantity, "excluded_quantity": decision.excluded_quantity,
            "reason": decision.reason, "history_orders": decision.history_orders,
            "median_quantity": decision.median_quantity, "threshold": decision.threshold}


def main():
    started = perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    paths = [Path(__file__), Path(base.__file__), Path(__file__).with_name("backtest_intermittent.py"), POLICY_PATH]
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    previous = json.loads((base.OUT / "results.json").read_text(encoding="utf-8"))
    with (base.OUT / "predictions.csv").open(encoding="utf-8-sig", newline="") as stream:
        saved = list(csv.DictReader(stream))
    identity = lambda r: (r["supplier"], r["sku"], r["unit"], r["origin"], int(r["horizon"]))
    baseline = {identity(r): r for r in saved}
    origins = [date.fromisoformat(s) for s in previous["origin_dates"]]
    rows, sources, audits, ledger, adjustments, cleaned_daily = [], [], [], [], [], []
    for folder in sorted((base.ROOT / "docs/data").iterdir()):
        source_rows = []
        keys, _, matrix, _, metadata = base.load_supplier(folder, source_rows)
        expected = next(s for s in previous["source_files"] if s["supplier"] == folder.name)
        assert metadata["sha256"] == expected["sha256"] and metadata["warehouses"] == ["Алматы"]
        sources.append({"supplier": folder.name, **metadata})
        orders, movement_rows = prepare_orders(folder, source_rows)
        ledger.extend(movement_rows)
        # Grouping lines must conserve every SKU/day target and training value.
        raw_decisions = [CleaningDecision(o, o.quantity, "raw", 0) for o in orders]
        assert np.allclose(matrix_from_decisions(keys, raw_decisions, matrix.shape[1]), matrix, rtol=1e-12)
        history = CleaningHistory(orders, keys)
        adjustments.extend(decision_row(d) for d in history.full)
        final_clean = matrix_from_decisions(keys, history.full, matrix.shape[1])
        for i, key in enumerate(keys):
            for offset in np.flatnonzero(matrix[i]):
                cleaned_daily.append({"supplier": folder.name, "sku": key[0], "unit": key[1],
                                      "day": base.START + timedelta(days=int(offset)),
                                      "raw_quantity": matrix[i, offset], "regular_quantity": final_clean[i, offset]})
        # Independent full-prefix calculation verifies the cached optimization at two boundaries.
        for origin in (origins[0], origins[-1]):
            direct = clean_orders(orders, as_of=origin)
            cached, _ = history.at(origin)
            assert np.array_equal(cached, matrix_from_decisions(keys, direct, cached.shape[1]))
        first = np.argmax(matrix > 0, axis=1)
        for origin in origins:
            offset = (origin - base.START).days
            clean, decisions = history.at(origin)
            for unit in sorted({k[1] for k in keys}):
                subset = [d for d in decisions if d.order.unit == unit]
                audits.append({"supplier": folder.name, "unit": unit, "origin": origin.isoformat(),
                               "orders": len(subset), "flagged_orders": sum(d.excluded_quantity > 0 for d in subset),
                               "raw_quantity": float(sum(d.order.quantity for d in subset)),
                               "removed_quantity": float(sum(d.excluded_quantity for d in subset))})
            eligible = np.flatnonzero(first <= offset - 90)
            for horizon in (7, 28):
                raw_forecasts = base.forecast(matrix[eligible, :offset], horizon)
                clean_forecasts = base.forecast(clean[eligible], horizon)
                for j, i in enumerate(eligible):
                    key = (folder.name, *keys[i], origin.isoformat(), horizon)
                    old = baseline[key]
                    actual = float(matrix[i, offset:offset + horizon].sum())
                    assert actual == float(old["actual"])
                    assert all(np.isclose(raw_forecasts[m][j], float(old[m]), rtol=1e-12) for m in base.MODELS)
                    rows.append({"supplier": key[0], "sku": key[1], "unit": key[2], "origin": key[3],
                                 "horizon": horizon, "segment": old["segment"], "actual": actual,
                                 "phase": "development_2025" if origin.year == 2025 else "retrospective_2026",
                                 "baseline_selected": float(old["selected_2025"]),
                                 **{m: float(v[j]) for m, v in raw_forecasts.items()},
                                 **{f"clean_{m}": float(v[j]) for m, v in clean_forecasts.items()}})
            print(json.dumps({"supplier": folder.name, "origin": str(origin), "cleaning": "complete"}), flush=True)
    assert len(rows) == len(baseline) and {identity(r) for r in rows} == set(baseline)
    development = defaultdict(list)
    for row in rows:
        if row["phase"] == "development_2025":
            development[(row["supplier"], row["unit"], row["horizon"])].append(row)
    selections = {k: min(base.SHORT_MODELS, key=lambda m: score(v, f"clean_{m}")["wape_pct"])
                  for k, v in development.items()}
    raw_selection = {(r["supplier"], r["unit"], r["horizon"]): r["model"]
                     for r in previous["models_selected_using_2025_only"]}
    for row in rows:
        key = (row["supplier"], row["unit"], row["horizon"])
        row["clean_selected"] = row[f"clean_{selections[key]}"]
        row["clean_fixed_baseline"] = row[f"clean_{raw_selection[key]}"]
    models = ["baseline_selected", "clean_fixed_baseline", "clean_selected",
              *base.MODELS, *[f"clean_{m}" for m in base.MODELS]]
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
    for name, values in (("predictions", rows), ("metrics", metrics), ("monthly_metrics", monthly_metrics),
                         ("movement_ledger", ledger), ("order_decisions", adjustments),
                         ("cleaned_daily", cleaned_daily), ("cleaning_by_origin", audits)):
        base.write_csv(OUT / f"{name}.csv", values)
    summary = {"protocol": POLICY_VERSION + "; paired raw/clean history; unchanged gross targets",
               "source_files": sources, "script_sha256": hashes, "rows": len(rows),
               "baseline_results_sha256": hashlib.sha256((base.OUT / "results.json").read_bytes()).hexdigest(),
               "elapsed_seconds": perf_counter() - started, "metrics": metrics,
               "movement_reasons": dict(Counter(r["movement_reason"] for r in ledger)),
               "order_reasons": dict(Counter(r["reason"] for r in adjustments)),
               "cleaning_by_origin": audits, "comparison_is_retrospective": True,
               "selection": [{"supplier": k[0], "unit": k[1], "horizon": k[2], "model": v}
                             for k, v in selections.items()],
               "policy": {"lookback_days": 56, "min_orders": 8, "min_active_days": 4,
                          "threshold": "max(4*median, median+6*MAD)", "replacement": "past median",
                          "growth_guard": "3 elevated distinct days within +/-7 days strictly before origin"},
               "environment": {"python": sys.version, "numpy": np.__version__, "openpyxl": openpyxl.__version__,
                               "platform": platform.platform()},
               "source_and_baseline_reconciliation": "all keys/actuals/raw forecasts; exact cached/full-prefix checks"}
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (OUT / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "seconds": summary["elapsed_seconds"],
                      "order_reasons": summary["order_reasons"]}), flush=True)


if __name__ == "__main__":
    main()
