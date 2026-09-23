"""Read supplied movement workbooks with the same exact XML normalization as ingestion."""

import hashlib
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from replenishment.evaluation.runner import END, START
from replenishment.intake.adapters.normalization import number, value
from replenishment.intake.adapters.xlsx import Workbook


def load_sources(data_dir: Path, *, warehouse="Алматы", start=START, end=END):
    paths = sorted(path for path in data_dir.rglob("*.xlsx") if path.name.startswith("Динамика"))
    if not paths:
        raise ValueError(f"No supplied sales movement workbooks found in {data_dir}")
    series, provenance, seen_suppliers = [], [], set()
    for path in paths:
        supplier = path.parent.name
        if supplier in seen_suppliers:
            raise ValueError("Multiple movement workbooks for one supplier; select one source version")
        seen_suppliers.add(supplier)
        content = path.read_bytes()
        book = Workbook(content)
        groups, names, counts = defaultdict(lambda: defaultdict(Decimal)), {}, Counter()
        try:
            sheet = book.sheets[0]
            for row_number, cells in book.rows(sheet):
                if row_number == 1:
                    if value(cells, "A") != "Дата" or value(cells, "D") != "Код":
                        raise ValueError(f"Unrecognized movement header: {path}")
                    continue
                stamp, sku = value(cells, "A"), value(cells, "D")
                if stamp is None or sku is None:
                    counts["missing_identity_or_footer"] += 1
                    continue
                counts["source_rows"] += 1
                day = datetime.strptime(str(stamp), "%d.%m.%Y %H:%M:%S").date()
                if not start <= day <= end:
                    counts["outside_experiment_dates"] += 1
                    continue
                if value(cells, "G") != warehouse:
                    counts["other_warehouse"] += 1
                    continue
                quantity, document = number(cells, "H"), str(value(cells, "C") or "")
                if quantity is None:
                    counts["missing_or_invalid_qty"] += 1
                elif quantity <= 0 or not document.startswith("Расходная накладная"):
                    counts["ambiguous_or_non_outgoing_rows"] += 1
                else:
                    key = (str(sku), str(value(cells, "F")))
                    groups[key][(day, str(value(cells, "B")) + " | " + document)] += quantity
                    names.setdefault(key, str(value(cells, "E") or ""))
                    counts["included_positive_outgoing_rows"] += 1
        finally:
            book.close()
        for (sku, unit), documents in sorted(groups.items()):
            series.append({
                "supplier": supplier, "warehouse": warehouse, "unit": unit, "sku": sku,
                "name": names[(sku, unit)], "start": start, "end": end,
                "sales": [{"day": day, "quantity": quantity, "document": document}
                          for (day, document), quantity in sorted(documents.items())],
            })
        provenance.append({"supplier": supplier, "source": str(path.resolve()),
                           "sha256": hashlib.sha256(content).hexdigest(), "sheet": sheet.name,
                           "columns": "A:H", "counts": dict(counts)})
    return series, provenance
