"""Pinned monthly reports -> complete candidate ledger, without database access."""

import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from itertools import chain, islice
from pathlib import Path

from replenishment.intake.adapters.normalization import classify, observations, value
from replenishment.intake.adapters.xlsx import Workbook

ROOT = Path(__file__).resolve().parents[3]


def read_batch(planning_date="2026-09-22", root=ROOT, *, kind="monthly_sales"):
    """Load the pinned monthly workbooks into the V2 calculation boundary.

    This is a read-only research adapter.  It deliberately selects the two
    dedicated monthly reports and leaves unit/scope unknown when the source
    workbook does not establish them.
    """

    if kind not in {"monthly_sales", "monthly_stock"}:
        raise ValueError("Unsupported monthly report")
    label = "Ежемесячные продажи" if kind == "monthly_sales" else "Ежемесячные остатки"
    cutoff = planning_date[:7]
    manifest = json.loads((root / "docs/sources/manifest.json").read_text())
    selected = sorted(
        (entry for entry in manifest if label in entry.get("path", "")),
        key=lambda entry: entry["path"],
    )
    if len(selected) != 2:
        raise ValueError("Expected both pinned monthly workbooks")
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
                mapping = classify(headers, supplier)
                mapped_kind, header_end, sku_col, _, _, unit_col = mapping
                if mapped_kind != kind:
                    continue
                for row, cells in chain(prefix, iterator):
                    if row <= header_end:
                        continue
                    sku = value(cells, sku_col)
                    if not isinstance(sku, str) or not sku.strip():
                        continue
                    unit = value(cells, unit_col) if unit_col else None
                    for table, observation in observations(
                        kind, supplier, cells, row, headers, unit, None, mapping=mapping
                    ):
                        if table != kind:
                            continue
                        stamp = observation["month"].isoformat()
                        if kind == "monthly_sales" and stamp[:7] >= cutoff:
                            continue
                        records[(supplier, sku, unit, kind)].append(
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
            {
                "table": "demand_monthly_sales" if kind == "monthly_sales" else "inventory_monthly_stock",
                "path": entry["path"],
                "sha256": entry["sha256"],
            }
            for entry in selected
        ],
    }
