"""Mappings for the supplied IEK/Systeme templates. Values are observations, not policy."""

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from openpyxl.utils.cell import column_index_from_string, get_column_letter

MONTHS = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")


def value(cells, column):
    cell = cells.get(column, {})
    if cell.get("cached_type", cell.get("type")) == "e":
        return None
    return cell.get("cached_value") if cell.get("type") == "f" else cell.get("value")


def number(cells, column):
    cell = cells.get(column, {})
    if cell.get("cached_type", cell.get("type")) != "n":
        return None
    raw = value(cells, column)
    if raw is None or raw == "":
        return None
    try:
        result = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value at {column}: {raw!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Non-finite numeric value at {column}")
    if abs(result) >= Decimal("1e18"):
        raise ValueError(f"Value exceeds Numeric(30,12) at {column}: {raw}")
    with localcontext() as context:
        context.prec = max(40, len(result.as_tuple().digits) + 16)
        rounded = result.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP)
    if abs(rounded) >= Decimal("1e18"):
        raise ValueError(f"Value exceeds Numeric(30,12) at {column}: {raw}")
    return rounded


def month_header(label):
    text = str(label or "").lower().strip()
    year = re.search(r"\b(20\d{2})\b", text)
    for month, prefix in enumerate(MONTHS, 1):
        if text.startswith(prefix) and year:
            return date(int(year[1]), month, 1)
    return None


def classify(headers, supplier):
    first = headers.get(1, {})
    if value(first, "A") == "record_type" and value(first, "B") == "sku":
        return "csv", 1, "B", "C", None, "F"
    third = headers.get(3, {})
    if str(value(third, "A")).lower() == "год":
        return "seasonality", 3, None, None, None, None
    if value(first, "A") == "Дата" and value(first, "D") == "Код":
        return "movements", 1, "D", "E", None, "F"
    if str(value(headers.get(2, {}), "C")).strip().lower() == "код 1с":
        if supplier != "systeme":
            raise ValueError("TDSheet format requires Systeme supplier")
        return "snapshot", 2, "C", "D", "B", None
    if value(first, "E") in ("Мин. разр. к отгр.", "Кратность"):
        return ("moq", 1, "B", "D", "C", None) if supplier == "iek" else ("moq", 1, "C", "B", "D", None)
    if str(value(first, "A")).strip().lower() == "код 1с":
        return "shipments", 1, "A", "C", "B", None
    months = [c for c in first if month_header(value(first, c))]
    if months:
        if supplier == "iek":
            return (
                ("monthly_stock", 3, "C", "A", None, "B")
                if "D" == months[0]
                else ("monthly_sales", 2, "B", "A", None, None)
            )
        return (
            ("monthly_stock", 3, "C", "B", None, "D")
            if value(first, "A") == "№"
            else ("monthly_sales", 2, "B", "A", "C", None)
        )
    raise ValueError("Unsupported worksheet headers; workbook transaction cancelled")


def shipment_header(header):
    expected = re.search(r"поступление\s+(?:на|до)\s+(\d{2}\.\d{2}\.\d{4})", header, re.I)
    ordered = re.search(r"от\s+(\d{1,2})\s+([а-я]+)\s+(20\d{2})", header, re.I)
    ordered_on = None
    if ordered:
        for month, prefix in enumerate(MONTHS, 1):
            if ordered[2].startswith(prefix if prefix != "май" else "ма"):
                ordered_on = date(int(ordered[3]), month, int(ordered[1]))
    document = re.search(r"[А-ЯA-Z]{2}-\d+", header)
    return {
        "header": header,
        "document_number": document[0] if document else None,
        "ordered_on": ordered_on,
        "expected_on": datetime.strptime(expected[1], "%d.%m.%Y").date() if expected else None,
        "date_basis": "explicit" if expected else "unknown",
        "warehouse_id": None,
    }


def seasonality(cells, row, headers):
    """Known coordinate blocks; helper labels/years/month names stay raw, not fake metrics."""
    for column, cell in cells.items():
        index = column_index_from_string(column)
        year = month = None
        metric = label = None
        basis = "derived" if cell["type"] == "f" else "reported"
        if 4 <= row <= 6 and 2 <= index <= 14:
            year = 2020 + row
            month = index - 1 if index <= 13 else None
            metric = "monthly_total" if month else "annual_total"
            label = str(value(headers[3], column))
        elif 11 <= row <= 23 and 3 <= index <= 12:
            month = row - 10 if row <= 22 else None
            label = str(value(headers[10], column))
            if index == 12:
                metric = "final_coefficient" if month else "coefficient_average"
            else:
                year = 2024 + (index - 3) // 3
                metric = ("monthly_total", "seasonal_coefficient", "annual_share")[(index - 3) % 3]
                if month is None:
                    metric = "annual_total" if (index - 3) % 3 == 0 else "coefficient_summary"
            if row >= 20 and year == 2026:
                basis = "unknown"  # Future computed zeros do not establish zero demand.
        elif 11 <= row <= 13 and column in ("N", "O"):
            year = 2013 + row
            metric = "monthly_average" if column == "N" else "annual_total"
            label = str(value(headers[10], column))
        elif row == 15 and column == "N":
            metric, label = "adjustment", "Seasonality adjustment / Поправка сезонности"
        elif 28 <= row <= 39 and 3 <= index <= 7:
            month = row - 27
            year = {"C": 2025, "D": 2026}.get(column)
            metric = {
                "C": "seasonal_coefficient",
                "D": "seasonal_coefficient",
                "E": "average_coefficient",
                "F": "normalized_coefficient",
                "G": "annual_share",
            }[column]
            label = str(value(headers.get(27, {}), column))
            if row >= 37 and column in ("D", "E", "F", "G"):
                basis = "forecast"
        elif row == 40 and column in ("F", "G"):
            metric, label = "coefficient_summary", "Summary / Итого"
        if metric:
            yield (
                "seasonality",
                {
                    "source_column": column,
                    "year": year,
                    "month": month,
                    "metric": metric,
                    "label": label,
                    "value": number(cells, column),
                    "unit": None,
                    "basis": basis,
                },
            )


def observations(kind, supplier, cells, row, headers, unit, as_of):
    header = headers[2] if kind == "snapshot" else headers.get(1, {})
    if kind == "movements":
        timestamp = value(cells, "A")
        if not isinstance(timestamp, str):
            raise ValueError(f"Expected explicit movement timestamp, row {row}")
        yield (
            "movements",
            {
                "occurred_at": datetime.strptime(timestamp, "%d.%m.%Y %H:%M:%S"),
                "document_number": str(value(cells, "B")),
                "document_text": value(cells, "C"),
                "unit": unit,
                "warehouse_name": value(cells, "G"),
                "quantity": number(cells, "H"),
            },
        )
    if kind in ("monthly_sales", "monthly_stock", "snapshot"):
        for column in header:
            month = month_header(value(header, column))
            if month is None:
                continue
            item = {
                "source_column": column,
                "month": month,
                "quantity": number(cells, column),
                "unit": unit,
                "warehouse_id": None,
            }
            if kind == "monthly_stock":
                item["metric"] = "opening_stock" if supplier == "iek" else "stock_unspecified"
                yield "monthly_stock", item
            else:
                item["is_complete_period"] = None
                yield "monthly_sales", item
    rule_column = "E" if kind == "moq" else "D" if kind == "monthly_sales" and supplier == "systeme" else None
    if rule_column:
        yield (
            "quantity_rules",
            {
                "source_column": rule_column,
                "label": str(value(header, rule_column)),
                "kind": "minimum_shipment" if supplier == "iek" else "order_multiple",
                "value": number(cells, rule_column),
                "unit": unit,
                "interpretation_confirmed": False,
            },
        )
    if kind in ("shipments", "snapshot"):
        columns = [get_column_letter(i) for i in range(4, 10)] if kind == "shipments" else ["BC"]
        for column in columns:
            yield "shipment_lines", {"source_column": column, "quantity": number(cells, column), "unit": unit}
    metrics = {}
    if kind in ("monthly_stock", "monthly_sales"):
        metrics = {
            c: "stock_total" if kind == "monthly_stock" else "sales_total"
            for c in header
            if value(header, c) == "Итого"
        }
    if kind == "snapshot":
        metrics = {
            "F": "cost_unspecified",
            "S": "sales_total",
            "T": "sales_average",
            "AP": "sales_total",
            "AQ": "sales_average",
            "AR": "growth_change",
            "AS": "seasonality_change",
            "BA": "coverage_unspecified",
            "BB": "planned_order",
            "BH": "weight_unspecified",
        }
        for column, metric in zip(
            ("AT", "AU", "AV", "AW", "AX", "AY", "AZ"),
            ("showroom", "trading_area", "distribution_center", "retail", "on_hand", "reserved", "free"),
            strict=True,
        ):
            yield (
                "stock",
                {
                    "source_column": column,
                    "metric": metric,
                    "quantity": number(cells, column),
                    "unit": None,
                    "warehouse_id": None,
                    "scope_label": str(value(header, column)),
                    "as_of": as_of,
                    "date_basis": "filename" if as_of else "unknown",
                },
            )
    for column, metric in metrics.items():
        start = end = None
        if kind == "snapshot" and column in ("S", "T"):
            start, end = date(2024, 1, 1), date(2024, 12, 31)
        # AP/AQ's misleading label is not treated as a verified period.
        yield (
            "report_metrics",
            {
                "source_column": column,
                "metric": metric,
                "label": str(value(header, column)),
                "value": number(cells, column),
                "unit": None,
                "period_start": start,
                "period_end": end,
            },
        )
