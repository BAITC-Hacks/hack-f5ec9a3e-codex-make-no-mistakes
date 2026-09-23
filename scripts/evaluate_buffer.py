"""Fixed q90 horizon-residual calibration and explicitly synthetic inventory replay.

Consumes the verified experiment-1 artifacts; no database, training or network access.
"""

import argparse
import csv
import gzip
import hashlib
import json
import math
import random
import shutil
import time
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from evaluate_application_baseline import controls

HORIZON, QUANTILE = 21, 0.9


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def load_predictions(path):
    rows, seen = [], set()
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            if raw["model"] != "application" or raw["horizon"] != "21":
                continue
            key = tuple(raw[name] for name in ("supplier", "warehouse", "unit", "sku", "origin"))
            if key in seen:
                raise ValueError("Duplicate calibration target")
            seen.add(key)
            row = {name: raw[name] for name in ("supplier", "warehouse", "unit", "sku", "cohort", "segment")}
            row.update(
                origin=date.fromisoformat(raw["origin"]),
                actual=float(raw["actual"]),
                forecast=float(raw["forecast"]),
            )
            if any(not math.isfinite(row[name]) or row[name] < 0 for name in ("actual", "forecast")):
                raise ValueError("Invalid demand or forecast")
            row["residual"] = (row["actual"] - row["forecast"]) / max(row["forecast"], 1)
            rows.append(row)
    return rows


def calibrate(rows, origin, segment):
    """Nearest-rank quantile; only complete earlier labels, at most twelve origins."""
    eligible = [row for row in rows if row["origin"] + timedelta(days=HORIZON) <= origin]
    for scope in (segment, "supplier_unit"):
        subset = [row for row in eligible if scope == "supplier_unit" or row["segment"] == scope]
        origins = sorted({row["origin"] for row in subset})[-12:]
        if len(origins) >= 6:
            selected = [row for row in subset if row["origin"] in origins]
            values = sorted(row["residual"] for row in selected)
            return {
                "q": values[math.ceil(QUANTILE * len(values)) - 1],
                "scope": scope,
                "origin_count": len(origins),
                "n": len(values),
                "latest_label_end": (max(origins) + timedelta(days=HORIZON)).isoformat(),
            }
    return {"q": None, "scope": "insufficient_history", "origin_count": 0, "n": 0, "latest_label_end": None}


def targets(forecast, calibration):
    current = forecast * (1 + 7 / HORIZON)
    q = calibration["q"]
    candidate = current if q is None else forecast + max(0, q * max(forecast, 1))
    return current, candidate


def pinball(actual, target):
    error = actual - target
    return max(QUANTILE * error, (QUANTILE - 1) * error)


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        for segment in ("all", row["segment"]):
            key = (row["supplier"], row["unit"], row["cohort"], segment, row["policy"])
            groups[key].append(row)
    result = []
    for key, values in sorted(groups.items()):
        total = sum(row["actual"] for row in values)
        result.append(
            dict(zip(("supplier", "unit", "cohort", "segment", "policy"), key, strict=True))
            | {
                "n": len(values),
                "actual_qty": total,
                "pinball_mean": sum(pinball(row["actual"], row["target"]) for row in values) / len(values),
                "coverage_le_pct": 100 * sum(row["actual"] <= row["target"] for row in values) / len(values),
                "coverage_lt_pct": 100 * sum(row["actual"] < row["target"] for row in values) / len(values),
                "target_mean": sum(row["target"] for row in values) / len(values),
                "under_qty": sum(max(0, row["actual"] - row["target"]) for row in values),
                "over_qty": sum(max(0, row["target"] - row["actual"]) for row in values),
                "calibration_fallback_n": sum(row["scope"] == "insufficient_history" for row in values),
                "origin_count": len({row["origin"] for row in values}),
            }
        )
    return result


def replay(demand, review_targets, initial_stock, delay, backorder, warmup=28):
    """Arrivals, backlog service, review/order, then today's demand. All inputs synthetic policy state."""
    stock, backlog, pipeline = initial_stock, 0.0, defaultdict(float)
    served = unmet = total = inventory = backlog_days = order_qty = rounding = 0.0
    shortage_days = orders = 0
    for day, quantity in enumerate(demand):
        stock += pipeline.pop(day, 0.0)
        if backorder:
            fulfilled = min(stock, backlog)
            stock -= fulfilled
            backlog -= fulfilled
        if day in review_targets:
            raw = max(0, review_targets[day] - (stock + sum(pipeline.values()) - backlog))
            order = math.ceil(raw)  # Synthetic pieces: conversion=1, MOQ=0, multiple=1.
            if order:
                pipeline[day + 14 + delay] += order
            if day >= warmup:
                orders += order > 0
                order_qty += order
                rounding += order - raw
        fill = min(stock, quantity)
        stock -= fill
        miss = quantity - fill
        if backorder:
            backlog += miss
        if day >= warmup:
            total += quantity
            served += fill
            unmet += miss
            inventory += stock
            backlog_days += backlog
            shortage_days += miss > 1e-9
    n = len(demand) - warmup
    if n <= 0:
        raise ValueError("Replay must exceed warm-up")
    return {
        "demand": total,
        "immediately_served": served,
        "unmet_at_request": unmet,
        "fill_rate_pct": 100 * served / total if total else None,
        "average_stock": inventory / n,
        "stockout_days": shortage_days,
        "backlog_unit_days": backlog_days,
        "terminal_stock": stock,
        "terminal_backlog": backlog,
        "terminal_pipeline": sum(pipeline.values()),
        "orders": orders,
        "ordered_units": order_qty,
        "rounding_excess": rounding,
    }


def gates(summary, monthly):
    """Provisional retrospective screen; paired two-month blocks, never prospective promotion."""
    result = []
    for candidate in summary:
        if candidate["policy"] != "q90_residual" or candidate["segment"] != "all":
            continue
        identity = {name: candidate[name] for name in ("supplier", "unit", "cohort")}
        def match(row, identity=identity):
            return all(row[name] == value for name, value in identity.items())
        control = next(
            row for row in summary if match(row) and row["segment"] == "all" and row["policy"] == "safety7"
        )
        paired = {}
        for row in monthly:
            if match(row) and row["segment"] == "all":
                paired.setdefault(row["origin"], {})[row["policy"]] = row
        blocks = [paired[origin] for origin in sorted(paired)]
        rng, gains, coverage = random.Random(20260923), [], []
        for _ in range(2000):
            indices = []
            while len(indices) < len(blocks):
                start = rng.randrange(len(blocks) - 1)
                indices.extend((start, start + 1))
            sample = [blocks[index] for index in indices[: len(blocks)]]
            base_loss = sum(row["safety7"]["pinball_mean"] * row["safety7"]["n"] for row in sample)
            new_loss = sum(row["q90_residual"]["pinball_mean"] * row["q90_residual"]["n"] for row in sample)
            if base_loss:
                gains.append(100 * (base_loss - new_loss) / base_loss)
            coverage.append(
                sum(row["q90_residual"]["coverage_le_pct"] * row["q90_residual"]["n"] for row in sample)
                / sum(row["q90_residual"]["n"] for row in sample)
            )
        improvement = (
            100 * (1 - candidate["pinball_mean"] / control["pinball_mean"])
            if control["pinball_mean"]
            else None
        )
        result.append(
            identity
            | {
                "pinball_improvement_pct": improvement,
                "coverage_le_pct": candidate["coverage_le_pct"],
                "coverage_lt_pct": candidate["coverage_lt_pct"],
                "pinball_monthly_wins": sum(
                    row["q90_residual"]["pinball_mean"] < row["safety7"]["pinball_mean"] for row in blocks
                ),
                "origins": len(blocks),
                "descriptive_gain_95pct_interval": [sorted(gains)[49], sorted(gains)[1949]]
                if gains
                else None,
                "descriptive_coverage_95pct_interval": [sorted(coverage)[49], sorted(coverage)[1949]],
                "retrospective_screen_pass": improvement is not None
                and improvement >= 5
                and 85 <= candidate["coverage_le_pct"] <= 95,
                "promotion": "not_evaluable_without_fresh_period",
            }
        )
    return result


def run(source, output):
    started = time.perf_counter()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if not all(sha(source / name) == value for name, value in manifest["artifacts"].items()):
        raise ValueError("Experiment-1 artifacts changed")
    rows = load_predictions(source / "predictions.csv.gz")
    pools, cache = defaultdict(list), {}
    for row in rows:
        pools[(row["supplier"], row["unit"])].append(row)

    def calibration(supplier, unit, origin, segment):
        key = (supplier, unit, origin, segment)
        if key not in cache:
            cache[key] = calibrate(pools[(supplier, unit)], origin, segment)
        return cache[key]

    evaluated, excluded = [], 0
    for row in rows:
        fit = calibration(row["supplier"], row["unit"], row["origin"], row["segment"])
        if row["origin"].year == 2025:
            excluded += 1
            continue  # Six earlier monthly origins unavailable: no fabricated development calibration score.
        for policy, target in zip(("safety7", "q90_residual"), targets(row["forecast"], fit), strict=True):
            evaluated.append(
                row | {"origin": row["origin"].isoformat(), "policy": policy, "target": target, **fit}
            )
    output.mkdir(parents=True, exist_ok=False)
    with gzip.open(output / "buffer-predictions.csv.gz", "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(evaluated[0]))
        writer.writeheader()
        writer.writerows(evaluated)
    summary = summarize(evaluated)
    dump(output / "metrics.json", summary)
    monthly = []
    for origin in sorted({row["origin"] for row in evaluated}):
        monthly += [
            row | {"origin": origin} for row in summarize([r for r in evaluated if r["origin"] == origin])
        ]
    dump(output / "monthly-metrics.json", monthly)
    dump(output / "gates.json", gates(summary, monthly))

    # Fixed mature cohort at Jan1, positive recorded sales as an exogenous demand proxy.
    begin, end, history_begin = date(2026, 1, 1), date(2026, 8, 31), date(2025, 1, 1)
    names = {name.casefold(): name for name, unit in pools}
    daily, first = {}, {}
    with gzip.open(source / "database-movements.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            if raw["unit"] != "шт" or not raw["quantity"]:
                continue
            quantity = Decimal(raw["quantity"])
            if quantity <= 0 or not raw["document_text"].startswith("Расходная накладная"):
                continue
            supplier = names[raw["supplier_name"].casefold()]
            key = (supplier, raw["unit"], raw["sku"])
            day = date.fromisoformat(raw["occurred_at"][:10])
            if key not in daily:
                daily[key] = [Decimal(0)] * ((end - history_begin).days + 1)
            daily[key][(day - history_begin).days] += quantity
            first[key] = min(first.get(key, day), day)
    simulation = []
    length = (end - begin).days + 1
    for key, history in sorted(daily.items()):
        if first[key] > begin - timedelta(days=90):
            continue
        supplier, unit, sku = key
        review = {policy: {} for policy in ("safety7", "q90_residual")}
        for offset in range(0, length, 7):
            origin = begin + timedelta(days=offset)
            previous = history[: (origin - history_begin).days]
            forecast = float(
                (controls(previous, 21, supplier, unit)["weekly_ewma"] / 21).quantize(Decimal("1e-12")) * 21
            )
            weeks = [sum(previous[-7 * (i + 1) : len(previous) - 7 * i]) for i in range(8)]
            segment = "regular" if sum(value > 0 for value in weeks) >= 4 else "intermittent"
            fit = calibration(supplier, unit, origin, segment)
            for policy, target in zip(review, targets(forecast, fit), strict=True):
                review[policy][offset] = target
            if offset == 0:
                initial = forecast
        actual = [float(value) for value in history[(begin - history_begin).days :]]
        for policy, target in review.items():
            for delay in (0, 7):
                for backorder in (False, True):
                    simulation.append(
                        {
                            "supplier": supplier,
                            "unit": unit,
                            "sku": sku,
                            "policy": policy,
                            "delay_days": delay,
                            "demand_treatment": "backorder" if backorder else "lost_sales",
                            **replay(actual, target, initial, delay, backorder),
                        }
                    )
    with gzip.open(output / "simulation.csv.gz", "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(simulation[0]))
        writer.writeheader()
        writer.writerows(simulation)
    grouped = defaultdict(list)
    for row in simulation:
        grouped[(row["supplier"], row["policy"], row["delay_days"], row["demand_treatment"])].append(row)
    aggregated = []
    for key, values in sorted(grouped.items()):
        metrics = {
            field: sum(row[field] for row in values)
            for field in (
                "demand",
                "immediately_served",
                "unmet_at_request",
                "average_stock",
                "stockout_days",
                "backlog_unit_days",
                "terminal_stock",
                "terminal_backlog",
                "terminal_pipeline",
                "orders",
                "ordered_units",
                "rounding_excess",
            )
        }
        aggregated.append(
            dict(zip(("supplier", "policy", "delay_days", "demand_treatment"), key, strict=True))
            | metrics
            | {
                "sku_count": len(values),
                "fill_rate_pct": 100 * metrics["immediately_served"] / metrics["demand"],
            }
        )
    dump(output / "simulation-summary.json", aggregated)
    dump(
        output / "calibration.json",
        [
            {"supplier": key[0], "unit": key[1], "origin": key[2].isoformat(), "segment": key[3], **value}
            for key, value in sorted(cache.items())
        ],
    )
    shutil.copy2(__file__, output / "evaluate_buffer.py")
    shutil.copy2(Path(__file__).with_name("evaluate_application_baseline.py"),
                 output / "evaluate_application_baseline.py")
    dump(
        output / "manifest.json",
        {
            "source_manifest_sha256": sha(source / "manifest.json"),
            "source_directory": str(source.resolve()),
            "q": QUANTILE,
            "horizon": HORIZON,
            "minimum_origins": 6,
            "maximum_origins": 12,
            "quantile_method": "nearest rank ceil(q*n); rows equally weighted; both history cohorts in pool",
            "development_rows_not_scored": excluded,
            "retrospective_targets": len(evaluated) // 2,
            "simulation": "synthetic pieces only, MOQ0/multiple1/conversion1, weekly review, L14, delay0/7",
            "initial_inventory": "same Jan1 point forecast, zero backlog and pipeline",
            "demand_observation": (
                "full exogenous recorded demand visible even when simulated lost sales occur"
            ),
            "evaluation_dates": "Jan29-Aug31 after 28-day warm-up; terminal state and pipeline retained",
            "missing_operational_truth": "availability, receipts, costs, reservations, purchase constraints",
            "elapsed_seconds": time.perf_counter() - started,
            "artifacts": {path.name: sha(path) for path in output.iterdir() if path.is_file()},
        },
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "targets": len(evaluated) // 2,
                "simulated_sku_scenarios": len(simulation),
                "seconds": time.perf_counter() - started,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.output)
