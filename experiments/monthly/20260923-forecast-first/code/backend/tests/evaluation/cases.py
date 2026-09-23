"""Pinned monthly reports -> complete candidate ledger, without database access."""

import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from itertools import chain, islice
from pathlib import Path

from evaluation.contracts import VERSION
from replenishment.intake.adapters.normalization import classify, month_header, observations, value
from replenishment.intake.adapters.xlsx import Workbook

ROOT = Path(__file__).resolve().parents[3]


def read_batch(planning_date="2026-09-22", root=ROOT):
    """Load the pinned monthly workbooks into the V2 calculation boundary.

    This is a read-only research adapter.  It deliberately selects the two
    dedicated monthly reports and leaves unit/scope unknown when the source
    workbook does not establish them.
    """

    cutoff = planning_date[:7]
    manifest = json.loads((root / "docs/sources/manifest.json").read_text())
    selected = sorted(
        (entry for entry in manifest if "Ежемесячные продажи" in entry.get("path", "")),
        key=lambda entry: entry["path"],
    )
    if len(selected) != 2:
        raise ValueError("Expected both pinned monthly sales workbooks")
    records = defaultdict(list)
    for entry in selected:
        content = (root / entry["path"]).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != entry["sha256"] or len(content) != entry["bytes"]:
            raise ValueError(f"Source hash/size mismatch: {entry['path']}")
        supplier = "iek" if "/IEK/" in entry["path"] else "systeme"
        workbook = Workbook(content)
        try:
            for sheet in workbook.sheets:
                iterator = workbook.rows(sheet)
                prefix = list(islice(iterator, 3))
                headers = dict(prefix)
                kind, header_end, sku_col, _, _, unit_col = classify(headers, supplier)
                if kind != "monthly_sales":
                    continue
                for row, cells in chain(prefix, iterator):
                    if row <= header_end:
                        continue
                    sku = value(cells, sku_col)
                    if not isinstance(sku, str) or not sku.strip():
                        continue
                    unit = value(cells, unit_col) if unit_col else None
                    for table, observation in observations(kind, supplier, cells, row, headers, unit, None):
                        if table != "monthly_sales":
                            continue
                        stamp = observation["month"].isoformat()
                        if stamp[:7] >= cutoff:
                            continue
                        records[(supplier, sku, unit, "monthly_sales")].append(
                            {
                                "month": stamp,
                                "quantity": observation["quantity"],
                                "evidence": [
                                    {
                                        "path": entry["path"],
                                        "sha256": digest,
                                        "sheet": sheet.name,
                                        "cell": f"{observation['source_column']}{row}",
                                    }
                                ],
                            }
                        )
        finally:
            workbook.close()
    series = []
    for (supplier, sku, unit, scope), observations_for_series in sorted(records.items(), key=repr):
        by_month = defaultdict(list)
        for observation in observations_for_series:
            by_month[observation["month"]].append(observation)
        history = []
        assumptions = []
        for stamp, values in sorted(by_month.items()):
            quantities = {item["quantity"] for item in values}
            quantity = next(iter(quantities)) if len(quantities) == 1 else None
            if len(quantities) > 1:
                assumptions.append({"kind": "conflicting_observation", "month": stamp})
            if quantity is not None and Decimal(str(quantity)) < 0:
                assumptions.append({"kind": "invalid_negative_sales", "month": stamp})
            history.append(
                {
                    "month": stamp,
                    "quantity": None if quantity is None else format(Decimal(str(quantity)), "f"),
                    "evidence": [e for item in values for e in item["evidence"]],
                }
            )
        identity = [supplier, sku, scope, unit]
        series_id = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        series.append(
            {
                "series_id": series_id,
                "supplier": supplier,
                "sku": sku,
                "scope": scope,
                "unit": unit,
                "history": history,
                "category": None,
                "inventory": None,
                "shipments": [],
                "quantity_rules": [],
                "assumptions": assumptions,
            }
        )
    return {
        "contract_version": "2",
        "planning_date": planning_date,
        "series": series,
        "parameters": {"history_cutoff": f"{cutoff}-01", "missing_months_preserved": True},
        "source_selection": [
            {"table": "demand_monthly_sales", "path": entry["path"], "sha256": entry["sha256"]}
            for entry in selected
        ],
    }


def assemble(records, year):
    """Records stay separate from requests; missing months are never imputed."""
    grouped = defaultdict(lambda: defaultdict(list))
    for record in records:
        grouped[(record["supplier"], record["sku"], record["unit"])][record["month"]].append(record)
    cases = []
    for (supplier, sku, unit), months in sorted(grouped.items(), key=lambda pair: repr(pair[0])):
        for target in range(2, 13):
            origin, target_month = f"{year}-{target - 1:02}", f"{year}-{target:02}"
            reasons, history = [], []
            evidence = []
            for stamp in sorted(set(months) | {origin, target_month}):
                if stamp > target_month:
                    continue
                values = months.get(stamp, [])
                sources = [r["source"] for r in values]
                evidence.extend(sources)
                quantities = {r["quantity"] for r in values}
                issue = (
                    "missing_observation"
                    if not values
                    else "conflicting_observation"
                    if len(quantities) != 1
                    else "blank_observation"
                    if None in quantities
                    else "negative_observation"
                    if next(iter(quantities)) < 0
                    else None
                )
                if issue:
                    if stamp in (origin, target_month):
                        reasons.append(f"{issue}:{stamp}")
                    continue
                if stamp < target_month:
                    history.append(
                        {"month": stamp, "quantity": format(next(iter(quantities)), "f"), "sources": sources}
                    )
            if not isinstance(unit, str) or not unit.strip():
                reasons.append("unknown_unit")
            actuals = months.get(target_month, [])
            actual_values = {r["quantity"] for r in actuals}
            actual = next(iter(actual_values)) if len(actual_values) == 1 else None
            if actual is not None and actual < 0:
                actual = None
            identity = {
                "contract_version": VERSION,
                "supplier": supplier,
                "sku": sku,
                "unit": unit,
                "target_month": target_month,
            }
            identity["case_id"] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            request = (
                {
                    **identity,
                    "origin": origin,
                    "history": history,
                    "stock": None,
                    "receipts": None,
                    "constraints": None,
                }
                if not reasons
                else None
            )
            cases.append(
                {
                    **identity,
                    "origin": origin,
                    "actual": format(actual, "f") if actual is not None else None,
                    "sources": evidence,
                    "forecast_eligible": not reasons,
                    "eligibility_reasons": reasons,
                    "inventory_eligible": False,
                    "inventory_reasons": ["stock_timing_scope_unconfirmed", "historical_receipts_missing"],
                    "request": request,
                }
            )
    return cases


def read_cases(year=2024, root=ROOT):
    if year != 2024:
        raise ValueError("Protocol v1 admits completed January–December 2024 only")
    manifest = json.loads((root / "docs/sources/manifest.json").read_text())
    selected = sorted(
        (entry for entry in manifest if "Ежемесячные продажи" in entry.get("path", "")),
        key=lambda entry: entry["path"],
    )
    if len(selected) != 2:
        raise ValueError("Expected both pinned monthly sales workbooks")
    records, sources, excluded = [], [], []
    rows_inspected = source_bytes = 0
    for entry in selected:
        content = (root / entry["path"]).read_bytes()
        source_bytes += len(content)
        digest = hashlib.sha256(content).hexdigest()
        if digest != entry["sha256"] or len(content) != entry["bytes"]:
            raise ValueError(f"Source hash/size mismatch: {entry['path']}")
        sources.append(entry)
        supplier = "iek" if "/IEK/" in entry["path"] else "systeme"
        workbook = Workbook(content)
        try:
            for sheet in workbook.sheets:
                iterator = workbook.rows(sheet)
                prefix = list(islice(iterator, 3))
                headers = dict(prefix)
                kind, header_end, sku_col, _, _, unit_col = classify(headers, supplier)
                if kind != "monthly_sales":
                    excluded.append(
                        {"path": entry["path"], "sheet": sheet.name, "reason": "supplier_aggregate"}
                    )
                    rows_inspected += len(prefix)
                    continue
                # A changed/missing month column is a corrupt protocol source, not a smaller cohort.
                present = {month_header(value(headers[1], c)) for c in headers[1]}
                if not all(any(d and d.year == year and d.month == m for d in present) for m in range(1, 13)):
                    raise ValueError("Missing required month columns")
                for row, cells in chain(prefix, iterator):
                    rows_inspected += 1
                    if row <= header_end:
                        continue
                    sku = value(cells, sku_col)
                    if sku is None or not str(sku).strip():
                        continue
                    if not isinstance(sku, str):
                        raise ValueError("SKU must remain a source string")
                    unit = value(cells, unit_col) if unit_col else None
                    for table, observation in observations(kind, supplier, cells, row, headers, unit, None):
                        if table != "monthly_sales" or observation["month"].year > year:
                            continue
                        records.append(
                            {
                                "supplier": supplier,
                                "sku": sku,
                                "unit": unit,
                                "month": observation["month"].strftime("%Y-%m"),
                                "quantity": observation["quantity"],
                                "source": {
                                    "path": entry["path"],
                                    "sha256": digest,
                                    "sheet": sheet.name,
                                    "cell": f"{observation['source_column']}{row}",
                                },
                            }
                        )
        finally:
            workbook.close()
    return (
        assemble(records, year),
        sources,
        {
            "source_bytes_opened": source_bytes,
            "rows_inspected": rows_inspected,
            "observations_read": len(records),
            "excluded_sheets": excluded,
            "scope": "Monthly sales adapter pass; source bytes count file content, not physical disk reads. "
            "Rows inspected count yielded rows including headers, not internal XML passes.",
        },
    )
