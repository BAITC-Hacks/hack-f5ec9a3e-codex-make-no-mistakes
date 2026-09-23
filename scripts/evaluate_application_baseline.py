"""Read-only PostgreSQL replay of the actual application, with immutable local evidence.

Run with the application's existing Python environment and DATABASE_URL configured.
No database tests, migrations, writes, training, or workbook reads are performed.
"""

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from statistics import median

START, END = date(2025, 1, 1), date(2026, 8, 31)
ORIGINS = [date(2025, month, 1) for month in range(7, 13)] + [date(2026, month, 1) for month in range(1, 9)]
HORIZONS = (7, 21, 28)
ZERO = Decimal(0)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8"
    )


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def controls(history, horizon, supplier, unit):
    """Independent weekly arithmetic, including the frozen legacy model choice."""
    weeks = [sum(history[-7 * (index + 1) : len(history) - 7 * index], ZERO) for index in range(8)]
    weights = [Decimal("0.72") ** index for index in range(8)]
    cap = 2 * median([value for value in weeks if value > 0]) if any(weeks) else ZERO
    raw = sum((value * weight for value, weight in zip(weeks, weights, strict=True)), ZERO)
    capped = sum((min(value, cap) * weight for value, weight in zip(weeks, weights, strict=True)), ZERO)
    selected = capped / sum(weights) / 7 * horizon
    if horizon == 7 and supplier == "IEK" and unit == "упак":
        selected = sum(history[-59:], ZERO) / 59 * horizon
    return {
        "weekly_ewma": raw / sum(weights) / 7 * horizon,
        "mean28": sum(history[-28:], ZERO) / 28 * horizon,
        "legacy_selected" if horizon != 21 else "capped_ewma_fixed": selected,
    }


def scales(history, horizon):
    blocks = [sum(history[end - horizon : end], ZERO) for end in range(len(history), horizon - 1, -horizon)][
        ::-1
    ]
    errors = [right - left for left, right in pairwise(blocks)]
    if not errors:
        return None, None
    return sum(map(abs, errors)) / len(errors), sum(value * value for value in errors) / len(errors)


def score(rows, metric_function, monthly=False):
    groups = defaultdict(list)
    for row in rows:
        for segment in ("all", row["segment"]):
            key = tuple(
                row[field]
                for field in ("phase", "supplier", "warehouse", "unit", "horizon", "cohort", "model")
            ) + (segment,)
            if monthly:
                key += (row["origin"],)
            groups[key].append(row)
    fields = ["phase", "supplier", "warehouse", "unit", "horizon", "cohort", "model", "segment"]
    if monthly:
        fields.append("origin")
    result = []
    for key, values in sorted(groups.items()):
        result.append(
            dict(zip(fields, key, strict=True))
            | metric_function(
                [row["actual"] for row in values],
                [row["forecast"] for row in values],
                mae_scales=[row["mae_scale"] for row in values],
                mse_scales=[row["mse_scale"] for row in values],
            )
            | {
                "sku_count": len({row["sku"] for row in values}),
                "origin_count": len({row["origin"] for row in values}),
            }
        )
    return result


def evaluate(metadata, connection, output, archive):
    from replenishment.browsing.tables import projection
    from replenishment.calculation.contracts import Scenario, StockOverride
    from replenishment.calculation.engine import calculate
    from replenishment.calculation.reading import read_inputs, source_options
    from sqlalchemy import func, select

    options = [row for row in source_options(connection, metadata) if row["kind"] == "movements"]
    if len(options) != 2 or len({row["supplier_id"] for row in options}) != 2:
        raise ValueError("Expected exactly one movement source for each of two suppliers; pin explicitly")
    manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
    if digest(archive / "predictions.csv.gz") != manifest["files"]["predictions.csv.gz"]["archived_sha256"]:
        raise ValueError("Archived predictions do not match the registered hash")
    supplier_labels = {sha: name for name, sha in manifest["source_hashes"]}
    if {row["sha256"] for row in options} != {row[1] for row in manifest["source_hashes"]}:
        raise ValueError("PostgreSQL source hashes differ from the registered benchmark")
    predictions, coverage, provenance = [], [], []
    legacy = {}
    with gzip.open(archive / "predictions.csv.gz", "rt", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row["supplier"], row["unit"], row["sku"], row["origin"], int(row["horizon"]))
            if key in legacy:
                raise ValueError("Duplicate archived target")
            legacy[key] = row
    matched, max_parity, max_archive_error = set(), ZERO, ZERO
    joined, cols = projection(metadata, "movements")
    columns = (
        "product_id",
        "source_row_id",
        "occurred_at",
        "quantity",
        "document_number",
        "document_text",
        "unit",
        "warehouse_id",
        "sku",
        "supplier_name",
        "warehouse_name",
    )
    with gzip.open(output / "database-movements.csv.gz", "wt", encoding="utf-8", newline="") as evidence:
        writer = csv.DictWriter(evidence, fieldnames=[*columns, "sheet_id", "sha256", "normalizer_version"])
        writer.writeheader()
        for source in options:
            where = (
                cols["sheet_id"] == source["sheet_id"],
                cols["normalizer_version"] == source["normalizer_version"],
            )
            latest = connection.scalar(
                select(func.max(cols["occurred_at"])).select_from(joined).where(*where)
            )
            if latest.date() < END:
                raise ValueError("Extract ends before the declared benchmark coverage")
            rows = [
                dict(row)
                for row in connection.execute(
                    select(*(cols[name].label(name) for name in columns))
                    .select_from(joined)
                    .where(
                        *where, cols["occurred_at"] >= START, cols["occurred_at"] < END + timedelta(days=1)
                    )
                ).mappings()
            ]
            for row in rows:
                writer.writerow(
                    row | {name: source[name] for name in ("sheet_id", "sha256", "normalizer_version")}
                )
            provenance.append(dict(source) | {"extracted_rows": len(rows), "latest_transaction": latest})
            groups = defaultdict(list)
            for row in rows:
                groups[(row["warehouse_id"], row["unit"])].append(row)
            for (warehouse, unit), movements in sorted(groups.items(), key=lambda item: str(item[0])):
                # Display capitalization differs; the workbook hash pins supplier identity.
                supplier = supplier_labels[source["sha256"]]
                warehouse_name = movements[0]["warehouse_name"]
                if warehouse_name != "Алматы":
                    raise ValueError("Legacy keys cannot represent additional warehouses")
                series, skus, first = {}, {}, {}
                for row in movements:
                    pid, day = row["product_id"], row["occurred_at"].date()
                    if row["quantity"] is None or row["quantity"] <= 0:
                        continue
                    if not row["document_text"].startswith("Расходная накладная"):
                        continue
                    if pid not in series:
                        series[pid] = [ZERO] * ((END - START).days + 1)
                    series[pid][(day - START).days] += row["quantity"]
                    skus[pid] = row["sku"]
                    first[pid] = min(first.get(pid, day), day)
                for origin in ORIGINS:
                    offset = (origin - START).days
                    known = {pid for pid in series if first[pid] < origin}
                    arguments = dict(
                        supplier_id=source["supplier_id"],
                        warehouse_id=warehouse,
                        unit=unit,
                        as_of=origin,
                        sales={name: source[name] for name in ("sheet_id", "normalizer_version")},
                        lead_time_days=14,
                        review_days=7,
                        safety_days=0,
                        confirm_no_incoming=True,
                    )
                    scenario = Scenario(**arguments)
                    inputs = read_inputs(connection, metadata, scenario)
                    expected_ids = {
                        row["source_row_id"]
                        for row in movements
                        if origin - timedelta(days=56) <= row["occurred_at"].date() < origin
                    }
                    actual_ids = [row["source_row_id"] for row in inputs["movements"]]
                    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != expected_ids:
                        raise ValueError("Application SQL history differs from the frozen projection")
                    for horizon in HORIZONS:
                        # Synthetic L/R isolates the forecast. Only H21 uses the UI's assumed L14/R7.
                        current = scenario.model_copy(
                            update={
                                "lead_time_days": 14 if horizon == 21 else 1,
                                "review_days": 7 if horizon == 21 else horizon - 1,
                            }
                        )
                        natural = {row["product_id"]: row for row in calculate(current, inputs)["items"]}
                        forced = current.model_copy(
                            update={
                                "stock_overrides": [
                                # Synthetic stock forces dormant output; no observed balance is claimed.
                                    StockOverride(sku=skus[pid], quantity=0)
                                    for pid in sorted(known, key=str)
                                ]
                            }
                        )
                        isolated = {row["product_id"]: row for row in calculate(forced, inputs)["items"]}
                        for pid in sorted(known, key=str):
                            history = series[pid][:offset]
                            mature = first[pid] <= origin - timedelta(days=90)
                            cohort = "legacy_mature" if mature else "recent_history"
                            actual = sum(series[pid][offset : offset + horizon], ZERO)
                            result = isolated[pid]
                            forecast = result["forecast"]
                            native = natural.get(pid)
                            if native and native["forecast"] != forecast:
                                raise ValueError("Synthetic stock changed demand forecast")
                            baselines = controls(history, horizon, supplier, unit)
                            parity = abs(forecast - baselines["weekly_ewma"])
                            max_parity = max(max_parity, parity)
                            if parity > Decimal(horizon) * Decimal("1e-12") + Decimal("1e-8"):
                                raise ValueError("Actual engine is not equivalent to the uncapped control")
                            if mature and horizon in (7, 28):
                                key = (supplier, unit, skus[pid], origin.isoformat(), horizon)
                                old = legacy[key]
                                if abs(actual - Decimal(old["actual"])) > Decimal("1e-8"):
                                    raise ValueError("PostgreSQL actual quantity differs from archive")
                                for name, old_name in (
                                    ("weekly_ewma", "weekly_ewma"),
                                    ("mean28", "mean28"),
                                    ("legacy_selected", "selected_2025"),
                                ):
                                    error = abs(baselines[name] - Decimal(old[old_name]))
                                    max_archive_error = max(max_archive_error, error)
                                    if error > Decimal("1e-7"):
                                        raise ValueError("Control prediction differs from archive")
                                if key in matched:
                                    raise ValueError("Duplicate scored target")
                                matched.add(key)
                            weeks = [
                                sum(history[-7 * (index + 1) : offset - 7 * index], ZERO)
                                for index in range(8)
                            ]
                            active = sum(value > 0 for value in weeks)
                            ma, ms = scales(history, horizon)
                            segment = "regular" if active >= 4 else "intermittent"
                            base = dict(
                                supplier=supplier,
                                warehouse=warehouse_name,
                                unit=unit,
                                sku=skus[pid],
                                origin=origin.isoformat(),
                                horizon=horizon,
                                cohort=cohort,
                                segment=segment,
                                phase="development_2025" if origin.year == 2025 else "retrospective_2026",
                                actual=actual,
                                mae_scale=ma,
                                mse_scale=ms,
                                native_emitted=native is not None,
                                positive_history=any(history[-56:]),
                                weekly_cap_binds=baselines["weekly_ewma"]
                                > (controls(history, 21, supplier, unit)["capped_ewma_fixed"] / 21 * horizon
                                   + Decimal("1e-8")),
                            )
                            for name, value in {"application": forecast, **baselines}.items():
                                predictions.append(base | {"model": name, "forecast": value})
                        coverage.append(
                            dict(
                                supplier=supplier,
                                unit=unit,
                                origin=origin,
                                horizon=horizon,
                                natural_rows=len(natural),
                                known_positive_history=len(known),
                                natural_known_rows=sum(pid in natural for pid in known),
                                omitted_known=sum(pid not in natural for pid in known),
                                history_status="synthetic zero stock only forces isolated forecast output",
                            )
                        )
                    print(f"Scored {supplier} / {unit} / {origin}: {len(known)} historical SKUs", flush=True)
    if matched != set(legacy):
        raise ValueError(f"Legacy target keys differ: {len(matched)} vs {len(legacy)}")
    return predictions, dict(
        sources=provenance,
        coverage=coverage,
        legacy_targets_matched=len(matched),
        max_engine_parity_error=max_parity,
        max_archive_control_error=max_archive_error,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get("DATABASE_URL"):
        parser.error("Set DATABASE_URL; it is never written into artifacts")
    sys.dont_write_bytecode = True
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    package = args.app_root / "backend/src/replenishment"
    source_hashes = {str(path.relative_to(package)): digest(path) for path in package.rglob("*.py")}
    shutil.copytree(package, args.output / "code/replenishment", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(args.metrics, args.output / "code/metrics.py")
    shutil.copy2(__file__, args.output / "code/evaluate_application_baseline.py")
    sys.path.insert(0, str((args.output / "code").resolve()))
    from replenishment.schema import metadata
    from sqlalchemy import create_engine, text

    metric_function = load_module("frozen_metrics", args.output / "code/metrics.py").forecast_metrics
    engine = create_engine(
        os.environ["DATABASE_URL"],
        connect_args={"options": "-c default_transaction_read_only=on -c statement_timeout=60000"},
    )
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                if connection.scalar(text("SHOW transaction_read_only")) != "on":
                    raise ValueError("Read-only transaction not established")
                predictions, evidence = evaluate(metadata, connection, args.output, args.archive)
    finally:
        engine.dispose()
    changed = [name for name, sha in source_hashes.items() if digest(package / name) != sha]
    if changed:
        raise ValueError(f"Application changed during evaluation: {changed}")
    with gzip.open(args.output / "predictions.csv.gz", "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    summary = score(predictions, metric_function)
    dump(args.output / "metrics.json", summary)
    dump(args.output / "monthly-metrics.json", score(predictions, metric_function, monthly=True))
    dump(args.output / "evidence.json", evidence)
    dump(
        args.output / "manifest.json",
        dict(
            created_at=datetime.now().astimezone().isoformat(),
            elapsed_seconds=time.perf_counter() - started,
            app_source_hashes=source_hashes,
            metrics_sha256=digest(args.output / "code/metrics.py"),
            script_sha256=digest(Path(__file__)),
            archive_manifest_sha256=digest(args.archive / "manifest.json"),
            prediction_rows=len(predictions),
            horizons=HORIZONS,
            origins=ORIGINS,
            source="PostgreSQL read-only repeatable-read",
            python=sys.version,
            completeness="Legacy Jan2025-Aug2026 extract completeness assumed; target equality checked",
            operational_metrics="not_evaluated: no historical stock/receipts/availability/cost truth",
            source_code_unchanged=True,
            artifacts={path.name: digest(path) for path in args.output.iterdir() if path.is_file()},
        ),
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": len(predictions),
                "matched_legacy_targets": evidence["legacy_targets_matched"],
                "seconds": round(time.perf_counter() - started, 2),
            }
        )
    )


if __name__ == "__main__":
    main()
