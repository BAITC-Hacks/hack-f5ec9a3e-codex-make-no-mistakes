"""Independent, read-only reconciliation of delivered Excel workbooks and PostgreSQL."""

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import zip_longest
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from sqlalchemy import create_engine, text

TABLES = {
    "demand_movements": "quantity",
    "demand_monthly_sales": "quantity",
    "inventory_monthly_stock": "quantity",
    "inventory_observations": "quantity",
    "supply_quantity_rules": "value",
    "supply_shipment_lines": "quantity",
    "demand_report_metrics": "value",
    "demand_seasonality_observations": "value",
}
MONTHS = "янв фев мар апр май июн июл авг сен окт ноя дек".split()
TOLERANCE = Decimal("0.00000001")


def numeric(cell):
    return Decimal(str(cell.value)) if cell.data_type == "n" and cell.value is not None else None


def equal_number(expected, actual):
    if expected is None or actual is None:
        return expected is actual
    if expected == expected.to_integral_value():
        return expected == actual
    return abs(expected - actual) <= TOLERANCE


def stats(values):
    values = list(values)
    numbers = [v for v in values if v is not None]
    return {
        "count": len(values),
        "null": len(values) - len(numbers),
        "negative": sum(v < 0 for v in numbers),
        "zero": numbers.count(0),
        "positive": sum(v > 0 for v in numbers),
        "sum": str(sum(numbers, Decimal(0))),
    }


def compare(expected, actual):
    """Compare coordinate+identity keys as well as values; aggregates cannot hide swaps."""
    missing = expected.keys() - actual.keys()
    extra = actual.keys() - expected.keys()
    changed = [k for k in expected.keys() & actual.keys() if not equal_number(expected[k], actual[k])]
    before, after = stats(expected.values()), stats(actual.values())
    distributions_equal = all(
        before[k] == after[k] for k in ("count", "null", "negative", "zero", "positive")
    )
    sum_tolerance = TOLERANCE * len(expected)
    sums_equal = abs(Decimal(before["sum"]) - Decimal(after["sum"])) <= sum_tolerance
    return {
        "expected": before,
        "actual": after,
        "distributions_equal": distributions_equal,
        "sums_equal": sums_equal,
        "sum_absolute_tolerance": str(sum_tolerance),
        "missing": len(missing),
        "extra": len(extra),
        "changed": len(changed),
        "examples": [
            {"key": list(k), "expected": str(expected.get(k)), "actual": str(actual.get(k))}
            for k in sorted(missing | extra | set(changed), key=str)[:10]
        ],
        "passed": not (missing or extra or changed) and distributions_equal and sums_equal,
    }


def template(path, sheet):
    """Explicit delivered-file contract, independent of the production header classifier."""
    ie = path.parent.name == "IEK"
    name = path.name.lower()
    if "сезонность" in name or sheet.title == "Лист1":
        return "seasonality", 0, 0
    if "динамика" in name:
        return "movements", 1, 4
    if "moq" in name:
        return "moq", 1, 2 if ie else 3
    if "остатки" in name:
        return "stock", 3, 3
    if "ежемесячные продажи" in name:
        return "sales", 2, 2
    if "пут" in name:
        return ("shipments", 1, 1) if ie else ("snapshot", 2, 3)
    raise ValueError(f"Unsupported source: {path.name}/{sheet.title}")


def month(value):
    label = str(value or "").lower()
    year = re.search(r"20\d{2}", label)
    for index, prefix in enumerate(MONTHS, 1):
        if label.startswith(prefix) and year:
            return date(int(year[0]), index, 1).isoformat()
    return None


def xml_numbers(payload):
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    return {
        cell.attrib["r"]: Decimal(cell.findtext(namespace + "v"))
        for cell in ElementTree.fromstring(payload).iter(namespace + "c")
        if cell.get("t", "n") == "n" and cell.findtext(namespace + "v")
    }


def expected_sheet(path, formulas, cached, exact_numbers=None):
    kind, header_end, sku_index = template(path, formulas)
    expected = {table: {} for table in TABLES}
    raw_rows, products = set(), {}
    warnings = Counter()
    headers = []
    for row_number, (source, values) in enumerate(zip_longest(formulas.rows, cached.rows), 1):
        if any(c.value is not None for c in source):
            raw_rows.add(row_number)
        for cell, value in zip(source, values, strict=True):
            warnings["excel_errors"] += value.data_type == "e"
            warnings["formula_cache_missing"] += cell.data_type == "f" and value.value is None
        if row_number == (2 if kind == "snapshot" else 1):
            headers = [c.value for c in values]
        if kind == "seasonality":
            # Delivered numeric blocks; labels/helper month numbers stay raw.
            for column, cell in enumerate(source, 1):
                included = (
                    (4 <= row_number <= 6 and 2 <= column <= 14)
                    or (11 <= row_number <= 23 and 3 <= column <= 12)
                    or (11 <= row_number <= 13 and column in (14, 15))
                    or (row_number == 15 and column == 14)
                    or (28 <= row_number <= 39 and 3 <= column <= 7)
                    or (row_number == 40 and column in (6, 7))
                )
                if included and cell.value is not None:
                    key = (row_number, get_column_letter(column), "", "")
                    expected["demand_seasonality_observations"][key] = (
                        exact_numbers.get(cell.coordinate)
                        if exact_numbers is not None
                        else numeric(values[column - 1])
                    )
            continue
        if row_number <= header_end:
            continue
        sku = values[sku_index - 1].value
        if sku is None or not str(sku).strip():
            continue
        products[row_number] = str(sku)

        def add(table, column, dimension="", row_number=row_number, sku=sku, values=values):
            key = (row_number, get_column_letter(column), str(sku), dimension)
            expected[table][key] = numeric(values[column - 1])

        if kind == "movements":
            add("demand_movements", 8)
        if kind in ("stock", "sales", "snapshot"):
            for column, label in enumerate(headers, 1):
                period = month(label)
                if period:
                    add(
                        "inventory_monthly_stock" if kind == "stock" else "demand_monthly_sales",
                        column,
                        period,
                    )
                if label == "Итого":
                    add("demand_report_metrics", column)
        if kind == "moq":
            add("supply_quantity_rules", 5)
        if kind == "sales" and path.parent.name != "IEK":
            add("supply_quantity_rules", 4)
        if kind == "shipments":
            for column in range(4, 10):
                add("supply_shipment_lines", column)
        if kind == "snapshot":
            for column in range(46, 53):
                add("inventory_observations", column)
            add("supply_shipment_lines", 55)
            for column in (6, 19, 20, 42, 43, 44, 45, 53, 54, 60):
                add("demand_report_metrics", column)
            on_hand, reserved, free = [numeric(values[i - 1]) for i in (50, 51, 52)]
            if None not in (on_hand, reserved, free):
                warnings["stock_identity_mismatch"] += not equal_number(on_hand - reserved, free)
            components = [numeric(values[i - 1]) for i in range(46, 50)]
            if on_hand is not None:
                warnings["stock_components_differ_from_total"] += sum(v or 0 for v in components) != on_hand
            warnings["thirteen_month_formula"] += source[41].value == f"=SUM(AC{row_number}:AO{row_number})"
            warnings["average_formula_not_divided_by_12"] += (
                source[42].data_type == "f" and source[42].value != f"=AP{row_number}/12"
            )
    if kind != "movements":
        warnings["duplicate_sku_rows"] = len(products) - len(set(products.values()))
    if kind in ("stock", "sales", "snapshot"):
        warnings["unknown_warehouse_scope"] = len(products)
    return expected, raw_rows, products, dict(warnings), kind


def actual_sheet(connection, sheet_id, version, supplier):
    actual, duplicates = {}, {}
    for table, quantity in TABLES.items():
        movement = table == "demand_movements"
        seasonal = table == "demand_seasonality_observations"
        column = "'H'" if movement else "t.source_column"
        period = "t.month::text" if table in ("demand_monthly_sales", "inventory_monthly_stock") else "''"
        identity = "''" if seasonal else "p.sku"
        sku = f"CASE WHEN s.code=:supplier THEN {identity} ELSE 'WRONG_SUPPLIER:' || s.code END"
        join = (
            "JOIN catalog_suppliers s ON s.id=t.supplier_id"
            if seasonal
            else "JOIN catalog_products p ON p.id=t.product_id JOIN catalog_suppliers s ON s.id=p.supplier_id"
        )
        rows = connection.execute(
            text(
                f"SELECT r.row_number, {column}, {sku}, {period}, t.{quantity} FROM {table} t "
                f"JOIN intake_rows r ON r.id=t.source_row_id {join} "
                "WHERE r.sheet_id=:sheet AND t.normalizer_version=:version"
            ),
            {"sheet": sheet_id, "version": version, "supplier": supplier},
        )
        records, count = {}, 0
        for record in rows:
            records[tuple(record[:4])] = record[4]
            count += 1
        actual[table] = records
        duplicates[table] = count - len(records)
    return actual, duplicates


def audit(connection, paths, version):
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "normalizer_version": version,
        "schema_revision": connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),
        "transaction_read_only": connection.execute(text("SHOW transaction_read_only")).scalar_one(),
        "transaction_isolation": connection.execute(text("SHOW transaction_isolation")).scalar_one(),
        "numeric_absolute_tolerance": str(TOLERANCE),
        "failures": [],
        "sheets": [],
        "workbooks": [],
        "limitations": [
            "Openpyxl float decoding: fractional tolerance 1e-8, integer values exact; "
            "total tolerance is number of observations times 1e-8. Original workbook bytes checked exactly.",
            "Large seasonal totals use independent XML decimal lexemes, avoiding openpyxl float loss.",
            "Raw row membership checked; individual JSONB cell contents/formulas/formats not re-compared.",
            "Typed numeric coordinates, SKU, monthly dates checked. Movement timestamps/documents/units, "
            "catalog attribute text, metric labels, seasonal year/month/basis and shipment dates "
            "not reconciled.",
            "No forecast accuracy, UI/API behavior or business correctness certification; "
            "source issues remain.",
            "Audit selected files/version only; other source versions may coexist in the database.",
        ],
    }
    identities = set()
    for path in paths:
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        stored = (
            connection.execute(
                text("SELECT id,content,byte_size FROM intake_workbooks WHERE sha256=:hash"), {"hash": digest}
            )
            .mappings()
            .one_or_none()
        )
        good = (
            stored is not None and bytes(stored["content"]) == payload and stored["byte_size"] == len(payload)
        )
        result["workbooks"].append({"file": path.name, "sha256": digest, "bytes_equal": good})
        if not good:
            result["failures"].append(f"Workbook missing/bytes mismatch: {path.name}")
            continue
        sheets = {
            s["name"]: s
            for s in connection.execute(
                text("SELECT id,name FROM intake_sheets WHERE workbook_id=:book"), {"book": stored["id"]}
            ).mappings()
        }
        source = load_workbook(path, read_only=True, data_only=False)
        cached = load_workbook(path, read_only=True, data_only=True)
        try:
            if set(source.sheetnames) != set(sheets):
                result["failures"].append(f"Sheet set mismatch: {path.name}")
            for worksheet in source:
                if worksheet.title not in sheets:
                    continue
                exact_numbers = None
                if template(path, worksheet)[0] == "seasonality":
                    with ZipFile(path) as archive:
                        exact_numbers = xml_numbers(archive.read(worksheet._worksheet_path))
                expected, raw, products, warnings, kind = expected_sheet(
                    path, worksheet, cached[worksheet.title], exact_numbers
                )
                supplier = "iek" if path.parent.name == "IEK" else "systeme"
                identities.update((supplier, sku) for sku in products.values())
                sheet_id = sheets[worksheet.title]["id"]
                actual, duplicates = actual_sheet(connection, sheet_id, version, supplier)
                db_raw = set(
                    connection.execute(
                        text("SELECT row_number FROM intake_rows WHERE sheet_id=:sheet"), {"sheet": sheet_id}
                    ).scalars()
                )
                db_products = dict(
                    connection.execute(
                        text(
                            "SELECT r.row_number,p.sku FROM catalog_product_observations o "
                            "JOIN intake_rows r ON r.id=o.source_row_id "
                            "JOIN catalog_products p ON p.id=o.product_id "
                            "JOIN catalog_suppliers s ON s.id=p.supplier_id "
                            "WHERE r.sheet_id=:sheet AND o.normalizer_version=:version AND s.code=:supplier"
                        ),
                        {"sheet": sheet_id, "version": version, "supplier": supplier},
                    )
                    .tuples()
                    .all()
                )
                tables = {t: compare(expected[t], actual[t]) for t in TABLES if expected[t] or actual[t]}
                passed = raw == db_raw and products == db_products and not any(duplicates.values())
                passed = passed and all(t["passed"] for t in tables.values())
                entry = {
                    "file": path.name,
                    "sheet": worksheet.title,
                    "kind": kind,
                    "passed": passed,
                    "raw_rows_expected": len(raw),
                    "raw_rows_actual": len(db_raw),
                    "raw_rows_missing": sorted(raw - db_raw)[:10],
                    "raw_rows_extra": sorted(db_raw - raw)[:10],
                    "product_observations_equal": products == db_products,
                    "duplicate_typed_keys": duplicates,
                    "source_warnings": warnings,
                    "tables": tables,
                }
                result["sheets"].append(entry)
                if not passed:
                    result["failures"].append(f"Reconciliation mismatch: {path.name}/{worksheet.title}")
        finally:
            source.close()
            cached.close()
    db_identities = set(
        connection.execute(
            text("SELECT s.code,p.sku FROM catalog_products p JOIN catalog_suppliers s ON s.id=p.supplier_id")
        ).tuples()
    )
    missing = identities - db_identities
    result["product_identities"] = {"expected_unique": len(identities), "missing": len(missing)}
    if missing:
        result["failures"].append("Missing supplier-scoped product identities")
    result["database_findings"] = [
        dict(r)
        for r in connection.execute(
            text(
                "SELECT code,count(*) AS records FROM intake_findings "
                "WHERE code <> 'import_complete' GROUP BY code ORDER BY code"
            )
        ).mappings()
    ]
    result["passed"] = not result["failures"]
    return result


def write_report(result, directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "data-quality.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    totals = defaultdict(int)
    quality = Counter()
    movement_quality = Counter()
    for sheet in result["sheets"]:
        for table, comparison in sheet["tables"].items():
            totals[table] += comparison["actual"]["count"]
        quality.update(sheet["source_warnings"])
        if "demand_movements" in sheet["tables"]:
            counts = sheet["tables"]["demand_movements"]["expected"]
            movement_quality.update({k: counts[k] for k in ("count", "negative", "null", "zero")})
    lines = [
        "# Качество данных / Data quality",
        "",
        f"Результат сверки / Reconciliation: **{'PASS' if result['passed'] else 'FAIL'}**.",
        f"Время / Generated: {result['generated_at']}. Версия / Version: {result['normalizer_version']}.",
        f"Книг / Workbooks: {len(result['workbooks'])}; листов / sheets: {len(result['sheets'])}.",
        "",
        "PASS означает совпадение проверенных полей, а не пригодность данных для прогноза.",
        "PASS means agreement within the stated coverage, not forecast readiness.",
        "",
        "## Типизированные наблюдения / Typed observations",
        "",
        "| Table | Rows |",
        "|---|---:|",
        *[f"| {table} | {count} |" for table, count in totals.items()],
        "",
        "## Сверка по листам / Per-sheet reconciliation",
        "",
        "| File / sheet | Raw rows | Result |",
        "|---|---:|---|",
        *[
            f"| {s['file']} / {s['sheet']} | {s['raw_rows_actual']} | {'PASS' if s['passed'] else 'FAIL'} |"
            for s in result["sheets"]
        ],
        "",
        "## Ограничения проверки / Coverage limits",
        "",
        "Все координаты числовых наблюдений сверены независимо через openpyxl; проверены SKU, "
        "месяцы, NULL, знаки и суммы. Оригинальные байты и множество непустых строк проверены полностью.",
        "All numeric observation coordinates, SKU, monthly dates, NULLs, signs and sums are independently "
        "reconciled via openpyxl; original bytes and nonempty row membership are checked.",
        "",
        *[f"- {gap}" for gap in result["limitations"]],
        "",
        "## Проблемы источников / Source issues",
        "",
        "Отрицательные движения, ошибки Excel, пропуски и неизвестный складской охват сохраняются. "
        "Они не являются ошибками импорта. Повторяющиеся сводки нельзя суммировать. "
        "Полные распределения и замечания по листам находятся в JSON.",
        "Negative movements, Excel errors, missing values and unknown warehouse scope remain source "
        "limitations, not import failures. Overlapping summaries must not be summed. See JSON for details.",
        "",
        "Независимый подсчёт в Excel / Independent Excel counts:",
        "",
        *[f"- movements_{code}: {count}" for code, count in movement_quality.items()],
        *[f"- {code}: {count}" for code, count in sorted(quality.items())],
        "",
        "Замечания уже записанные импортёром / Findings recorded by the importer "
        "(не независимая проверка / not independent validation):",
        "",
        *[f"- {x['code']}: {x['records']} DB findings" for x in result["database_findings"]],
        "",
        "## Ошибки сверки / Reconciliation failures",
        "",
        *([f"- {error}" for error in result["failures"]] or ["Нет / None."]),
        "",
    ]
    (directory / "data-quality.md").write_text("\n".join(lines), "utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("../docs/reports"))
    parser.add_argument("--normalizer-version", default="v1")
    args = parser.parse_args()
    paths = [args.path] if args.path.is_file() else sorted(args.path.rglob("*.xlsx"))
    paths = [p for p in paths if not p.name.startswith("~$")]
    if not paths:
        parser.error("No XLSX sources found")
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("DATABASE_URL is required")
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                result = audit(connection, paths, args.normalizer_version)
        write_report(result, args.output_dir)
        print(
            json.dumps(
                {"passed": result["passed"], "failures": result["failures"], "report": str(args.output_dir)},
                ensure_ascii=False,
            )
        )
        return 0 if result["passed"] else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
