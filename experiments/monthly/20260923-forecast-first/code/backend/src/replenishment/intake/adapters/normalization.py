"""Mappings for the supplied IEK/Systeme templates. Values are observations, not policy."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from openpyxl.utils.cell import column_index_from_string

MONTHS = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
MONTH_ALIASES = {
    "январь": 1,
    "янв": 1,
    "февраль": 2,
    "февр": 2,
    "фев": 2,
    "март": 3,
    "мар": 3,
    "апрель": 4,
    "апр": 4,
    "май": 5,
    "июнь": 6,
    "июн": 6,
    "июль": 7,
    "июл": 7,
    "август": 8,
    "авг": 8,
    "сентябрь": 9,
    "сент": 9,
    "сен": 9,
    "октябрь": 10,
    "окт": 10,
    "ноябрь": 11,
    "нояб": 11,
    "ноя": 11,
    "декабрь": 12,
    "дек": 12,
}


@dataclass(frozen=True)
class WorksheetMapping:
    """Validated coordinates for one supported worksheet layout."""

    kind: str
    header_end: int
    header_rows: tuple[int, ...]
    sku_col: str | None
    name_col: str | None
    article_col: str | None
    unit_col: str | None
    month_columns: tuple[tuple[str, date], ...] = ()
    field_columns: tuple[tuple[str, str], ...] = ()
    metric_columns: tuple[tuple[str, str], ...] = ()
    shipment_columns: tuple[str, ...] = ()
    source_cells: dict[str, tuple[str, ...]] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)

    def __iter__(self):
        # Existing evaluation code unpacks classify()'s historical tuple.
        yield from (self.kind, self.header_end, self.sku_col, self.name_col, self.article_col, self.unit_col)

    def __getitem__(self, index):
        return tuple(self)[index]

    @property
    def months(self):
        return dict(self.month_columns)

    @property
    def fields(self):
        return dict(self.field_columns)

    @property
    def metrics(self):
        return dict(self.metric_columns)

    def as_dict(self):
        return {
            "kind": self.kind,
            "header_end": self.header_end,
            "header_rows": list(self.header_rows),
            "sku_column": self.sku_col,
            "name_column": self.name_col,
            "article_column": self.article_col,
            "unit_column": self.unit_col,
            "month_columns": {column: period.isoformat() for column, period in self.month_columns},
            "field_columns": dict(self.field_columns),
            "metric_columns": dict(self.metric_columns),
            "shipment_columns": list(self.shipment_columns),
            "source_cells": {key: list(cells) for key, cells in self.source_cells.items()},
        }


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
    with localcontext() as context:
        context.prec = max(40, len(result.as_tuple().digits) + 16)
        rounded = result.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP)
    if abs(rounded) >= Decimal("1e18"):
        raise ValueError(f"Value exceeds Numeric(30,12) at {column}: {raw}")
    return rounded


def month_header(label):
    text = str(label or "").lower().strip()
    numeric = re.search(r"(20\d{2})[-/.](\d{1,2})", text)
    if numeric and text.startswith(numeric.group(1)):
        return date(int(numeric[1]), int(numeric[2]), 1)
    year = re.search(r"\b(20\d{2})\b", text)
    if not year:
        return None
    prefix = text[: year.start()].strip(" .-/") or text[year.end() :].strip(" .-/")
    prefix = prefix.split()[0] if prefix else ""
    for name, month in sorted(MONTH_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if prefix.startswith(name):
            return date(int(year[1]), month, 1)
    # A few exports put the year first (``2024 январь``) or use a numeric
    # month without a separator.  Keep this parser deliberately narrow: an
    # unrecognised header remains unresolved instead of becoming a guess.
    if text.startswith(year.group(1)):
        trailing = text[year.end() :].strip(" .-/")
        if trailing.isdigit() and 1 <= int(trailing) <= 12:
            return date(int(year[1]), int(trailing), 1)
        for name, month in sorted(MONTH_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if trailing.startswith(name):
                return date(int(year[1]), month, 1)
    return None


def _text(label):
    return re.sub(r"[^\w]+", " ", str(label or "").casefold()).strip()


def _rows(headers):
    return sorted((row, cells) for row, cells in headers.items() if isinstance(row, int))


def _labels(headers):
    return {
        (row, column): str(value(cells, column) or "")
        for row, cells in _rows(headers)
        for column in cells
        if value(cells, column) not in (None, "")
    }


def _column_for(headers, aliases, *, row=None, contains=False):
    aliases = tuple(_text(alias) for alias in aliases)
    for current_row, cells in _rows(headers):
        if row is not None and current_row != row:
            continue
        for column in cells:
            label = _text(value(cells, column))
            if any((alias in label if contains else label == alias) for alias in aliases):
                return column, str(value(cells, column))
    return None, None


def _column_on_row_or_any(headers, aliases, row):
    column, label = _column_for(headers, aliases, row=row)
    return (column, label) if column else _column_for(headers, aliases)


def _month_columns(headers):
    candidates = []
    all_columns = sorted({column for _, cells in _rows(headers) for column in cells})
    rows = _rows(headers)
    for current_row, _cells in _rows(headers):
        months = []
        for column in all_columns:
            parts = [
                str(value(row_cells, column))
                for row, row_cells in rows
                if row <= current_row and value(row_cells, column) not in (None, "")
            ]
            parsed = month_header(" ".join(parts))
            if parsed is not None:
                months.append((column, parsed))
        months = tuple(months)
        months = tuple(item for item in months if item[1] is not None)
        if months:
            candidates.append((len(months), current_row, months))
    # Prefer the densest month row; on ties use the upper row.  This matters
    # for two-level headers where the lower row repeats ``Количество``.
    return max(candidates, key=lambda item: (item[0], -item[1]), default=None)


def _header_end(headers, first_row, *, stock=False):
    end = first_row
    for row, cells in _rows(headers):
        if not first_row < row <= first_row + (3 if stock else 2):
            continue
        labels = [_text(value(cells, column)) for column in cells]
        if labels and all(label in {"количество", "нач остаток", "остаток", "остатки"} for label in labels):
            end = row
    return end


def _mapping(
    kind,
    header_end,
    header_rows,
    sku_col=None,
    name_col=None,
    article_col=None,
    unit_col=None,
    *,
    month_columns=(),
    field_columns=(),
    metric_columns=(),
    shipment_columns=(),
    labels=None,
):
    source_cells = {}
    for key, column in (
        ("sku", sku_col),
        ("name", name_col),
        ("article", article_col),
        ("unit", unit_col),
    ):
        if column:
            source_cells.setdefault(key, []).append(f"{column}{header_rows[0]}")
    for key, column in (*field_columns, *metric_columns):
        if column:
            source_cells.setdefault(key, []).append(f"{column}{header_rows[0]}")
    for column, _period in month_columns:
        source_cells.setdefault("months", []).append(f"{column}{header_rows[0]}")
    return WorksheetMapping(
        kind,
        header_end,
        tuple(header_rows),
        sku_col,
        name_col,
        article_col,
        unit_col,
        tuple(month_columns),
        tuple((key, column) for key, column in field_columns if column),
        tuple((key, column) for key, column in metric_columns if column),
        tuple(shipment_columns),
        {key: tuple(cells) for key, cells in source_cells.items()},
        labels or {},
    )


def resolve_mapping(headers, supplier):
    """Resolve a supported worksheet by labels and month context, never position alone."""
    supplier = str(supplier).casefold()
    rows = _rows(headers)
    labels = _labels(headers)
    all_text = " ".join(_text(label) for label in labels.values())
    season_row = next((row for row, cells in rows if _text(value(cells, "A")) in {"год", "year"}), None)
    if season_row is not None:
        return _mapping("seasonality", season_row, (season_row,), labels=labels)

    date_col, _ = _column_for(headers, ("дата", "дата и время"))
    quantity_col, _ = _column_for(headers, ("количество", "кол во", "кол-во"))
    code_col, _ = _column_for(headers, ("код", "код 1с", "номенклатура код"))
    if date_col and code_col and quantity_col:
        name_col, _ = _column_for(headers, ("документ", "номенклатура", "наименование"), contains=True)
        unit_col, _ = _column_for(headers, ("ед", "ед изм", "единица"))
        warehouse_col, _ = _column_for(headers, ("склад", "склад отправитель"))
        document_col, _ = _column_for(headers, ("номер", "№", "номер документа"))
        if not warehouse_col:
            raise ValueError("Movement worksheet has no warehouse column")
        return _mapping(
            "movements",
            rows[0][0] if rows else 1,
            (rows[0][0],),
            code_col,
            name_col,
            None,
            unit_col,
            field_columns=(
                ("timestamp", date_col),
                ("document_number", document_col),
                ("document_text", name_col),
                ("warehouse", warehouse_col),
                ("quantity", quantity_col),
            ),
            labels=labels,
        )

    month_row = _month_columns(headers)
    # ``Код 1с`` is the distinctive Systeme snapshot label.  Regular
    # monthly exports use ``Номенклатура.Код`` and are handled below.
    exact_code_col, _ = _column_on_row_or_any(headers, ("код 1с",), month_row[1] if month_row else None)
    if exact_code_col and month_row and supplier != "systeme":
        raise ValueError("TDSheet format requires Systeme supplier")
    if exact_code_col and month_row:
        row = month_row[1]
        sku_col = exact_code_col
        name_col, _ = _column_on_row_or_any(headers, ("наименование", "номенклатура"), row)
        article_col, _ = _column_on_row_or_any(headers, ("артикул поставщика", "артикул иэк", "артикул"), row)
        fields = [("category", _column_for(headers, ("категория",), row=row, contains=True)[0])]
        metrics = []
        metric_aliases = {
            "cost_unspecified": ("сс реал",),
            "sales_total": ("продажи 2024", "сумма последние 12 мес"),
            "sales_average": ("ср мес 2024", "ср мес за последние 12 мес"),
            "growth_change": ("кэф роста",),
            "seasonality_change": ("кэф сез",),
            "coverage_unspecified": ("запас",),
            "planned_order": ("заказ",),
            "weight_unspecified": ("вес",),
        }
        for metric, aliases in metric_aliases.items():
            column, _ = _column_for(headers, aliases, contains=True)
            if column:
                metrics.append((metric, column))
        stock_aliases = {
            "showroom": ("витрина",),
            "trading_area": ("остаток тз",),
            "distribution_center": ("рц",),
            "retail": ("розничный",),
            "on_hand": ("остаток",),
            "reserved": ("зарезерв",),
            "free": ("свобод",),
        }
        for metric, aliases in stock_aliases.items():
            column, _ = _column_for(headers, aliases, contains=metric != "on_hand")
            if column:
                metrics.append((metric, column))
        shipments = tuple(
            column
            for column, label in ((column, value(headers[row], column)) for column in headers[row])
            if "в пути" in _text(label) or "поступ" in _text(label)
        )
        return _mapping(
            "snapshot",
            row,
            (row,),
            sku_col,
            name_col,
            article_col,
            None,
            month_columns=month_row[2],
            field_columns=fields + [("shipment", column) for column in shipments],
            metric_columns=metrics,
            shipment_columns=shipments,
            labels=labels,
        )

    rule_col, _ = _column_for(headers, ("мин разр к отгр", "кратность"), contains=True)
    # Systeme's monthly sales export carries a quantity-rule column beside
    # its month columns.  A real MOQ sheet has no month row.
    if code_col and rule_col and not month_row:
        row = next((row for row, cells in rows if code_col in cells), rows[0][0] if rows else 1)
        name_col, _ = _column_on_row_or_any(headers, ("наименование", "номенклатура"), row)
        article_col, _ = _column_on_row_or_any(headers, ("артикул поставщика", "артикул иэк", "артикул"), row)
        return _mapping(
            "moq",
            row,
            (row,),
            code_col,
            name_col,
            article_col,
            None,
            field_columns=(("quantity_rule", rule_col),),
            labels=labels,
        )

    if code_col:
        row = next((row for row, cells in rows if code_col in cells), rows[0][0] if rows else 1)
        shipment_columns = tuple(
            column
            for column in headers[row]
            if column not in {code_col}
            and (
                shipment_header(str(value(headers[row], column)))["expected_on"] is not None
                or re.search(r"\bот\s+\d{1,2}\s+[а-я]+\s+20\d{2}", str(value(headers[row], column)), re.I)
            )
        )
        if shipment_columns:
            name_col, _ = _column_on_row_or_any(headers, ("наименование", "номенклатура"), row)
            article_col, _ = _column_on_row_or_any(headers, ("артикул", "артикул поставщика"), row)
            return _mapping(
                "shipments",
                row,
                (row,),
                code_col,
                name_col,
                article_col,
                None,
                shipment_columns=shipment_columns,
                labels=labels,
            )

    if month_row:
        _count, row, months = month_row
        sku_col, _ = _column_on_row_or_any(headers, ("код 1с", "номенклатура код", "код"), row)
        name_col, _ = _column_on_row_or_any(headers, ("наименование", "номенклатура"), row)
        article_col, _ = _column_on_row_or_any(headers, ("артикул поставщика", "артикул иэк", "артикул"), row)
        unit_col, _ = _column_on_row_or_any(headers, ("ед", "ед изм", "единица"), row)
        stock = (
            "остат" in all_text
            or "нач остаток" in all_text
            or any(
                str(value(headers[row], c) or "").strip().casefold() in {"№", "номер"} for c in headers[row]
            )
        )
        header_end = _header_end(headers, row, stock=stock)
        metric_columns = tuple(
            ("stock_total" if stock else "sales_total", column)
            for current_row, cells in rows
            if current_row <= header_end
            for column in cells
            if _text(value(cells, column)) in {"итого", "итого количество", "total"}
        )
        rule = _column_on_row_or_any(headers, ("кратность",), row)[0]
        fields = (("quantity_rule", rule),) if rule else ()
        return _mapping(
            "monthly_stock" if stock else "monthly_sales",
            header_end,
            tuple(range(min(current for current, _ in rows), header_end + 1)),
            sku_col,
            name_col,
            article_col,
            unit_col,
            month_columns=months,
            field_columns=fields,
            metric_columns=metric_columns,
            labels=labels,
        )
    raise ValueError("Unsupported worksheet headers; workbook transaction cancelled")


def classify(headers, supplier):
    return resolve_mapping(headers, supplier)


def mapping_from_payload(payload, headers, supplier):
    """Turn a validated, cited LLM mapping into the local mapping contract.

    The model may identify columns, but it never supplies row values.  Every
    cited coordinate is checked against the captured header cells before the
    mapping can reach the importer.
    """
    if not isinstance(payload, dict):
        raise ValueError("Worksheet mapping must be an object")
    report_type = payload.get("report_type")
    kinds = {
        "transactions": "movements",
        "stock": "monthly_stock",
        "monthly_sales": "monthly_sales",
        "snapshot": "snapshot",
        "shipments": "shipments",
        "quantity_rules": "moq",
    }
    kind = kinds.get(report_type)
    if kind is None:
        raise ValueError("Unknown worksheet report type")
    header_row = payload.get("header_row")
    data_start = payload.get("data_start_row")
    columns = payload.get("columns")
    citations = payload.get("source_cells")
    if not isinstance(header_row, int) or not isinstance(data_start, int) or data_start <= header_row:
        raise ValueError("Invalid worksheet header boundaries")
    if not isinstance(columns, dict) or not isinstance(citations, list):
        raise ValueError("Incomplete worksheet mapping")

    available = {f"{column}{row}" for row, cells in _rows(headers) for column in cells}
    cited = set()
    for item in citations:
        if not isinstance(item, dict) or not isinstance(item.get("cell"), str):
            raise ValueError("Invalid mapping citation")
        cell = item["cell"].upper()
        if cell in cited or cell not in available:
            raise ValueError(f"Invalid source cell: {cell}")
        cited.add(cell)
    cited_columns = {re.match(r"[A-Z]{1,3}", cell)[0] for cell in cited}

    def column(key, *, required=False):
        value_ = columns.get(key)
        if value_ is None:
            if required:
                raise ValueError(f"Missing mapped column: {key}")
            return None
        if not isinstance(value_, str) or not re.fullmatch(r"[A-Z]{1,3}", value_.upper()):
            raise ValueError(f"Invalid mapped column: {key}")
        return value_.upper()

    sku = column("sku", required=kind != "seasonality")
    name = column("name")
    article = column("article")
    unit = column("unit")
    months = []
    for item in columns.get("months", []):
        if not isinstance(item, dict) or not isinstance(item.get("column"), str):
            raise ValueError("Invalid month mapping")
        period = month_header(item.get("period"))
        if period is None:
            try:
                period = date.fromisoformat(str(item.get("period")))
            except (TypeError, ValueError):
                raise ValueError("Invalid mapped month") from None
        if period.day != 1:
            raise ValueError("Mapped month must start on day one")
        column_name = item["column"].upper()
        if not re.fullmatch(r"[A-Z]{1,3}", column_name):
            raise ValueError("Invalid mapped month column")
        source_period = month_header(
            " ".join(
                str(value(cells, column_name) or "")
                for row, cells in _rows(headers)
                if header_row <= row < data_start
            )
        )
        if source_period != period:
            raise ValueError("Mapped period disagrees with source header")
        months.append((column_name, period))
    if len({period for _, period in months}) != len(months):
        raise ValueError("Duplicate mapped month")
    if len({column for column, _ in months}) != len(months) or sku in {column for column, _ in months}:
        raise ValueError("Mapped columns must be unique")
    if kind in {"monthly_sales", "monthly_stock"} and not months:
        raise ValueError("Monthly report requires period columns")

    def pairs(key):
        values = columns.get(key, {})
        if key == "metrics" and isinstance(values, list):
            if any(not isinstance(v, dict) or set(v) != {"name", "column"} for v in values):
                raise ValueError("Invalid metric mapping")
            if len({v["name"] for v in values}) != len(values):
                raise ValueError("Duplicate metric mapping")
            values = {v["name"]: v["column"] for v in values}
        if not isinstance(values, dict):
            raise ValueError(f"Invalid mapped fields: {key}")
        result = []
        for field_name, field_column in values.items():
            if field_column is None:
                continue
            if not isinstance(field_name, str) or not isinstance(field_column, str):
                raise ValueError(f"Invalid mapped field: {field_name}")
            if not re.fullmatch(r"[A-Z]{1,3}", field_column.upper()):
                raise ValueError(f"Invalid mapped field column: {field_name}")
            result.append((field_name, field_column.upper()))
        return tuple(result)

    fields = pairs("fields")
    metrics = pairs("metrics")
    allowed_fields = {
        "timestamp",
        "quantity",
        "warehouse",
        "document_number",
        "document_text",
        "quantity_rule",
        "category",
    }
    allowed_metrics = {
        "sales_total",
        "sales_average",
        "stock_total",
        "showroom",
        "trading_area",
        "distribution_center",
        "retail",
        "on_hand",
        "reserved",
        "free",
        "growth_change",
        "seasonality_change",
        "coverage_unspecified",
        "planned_order",
        "cost_unspecified",
        "weight_unspecified",
    }
    if set(dict(fields)) - allowed_fields or set(dict(metrics)) - allowed_metrics:
        raise ValueError("Unsupported worksheet interpretation")
    if kind == "moq" and "quantity_rule" not in dict(fields):
        raise ValueError("Quantity rule mapping lacks a quantity column")
    if (
        kind == "movements"
        and not {"timestamp", "quantity", "warehouse", "document_number"} <= dict(fields).keys()
    ):
        raise ValueError("Movement mapping lacks required fields")
    shipments = columns.get("shipments", [])
    if not isinstance(shipments, list) or any(
        not isinstance(item, str) or not re.fullmatch(r"[A-Z]{1,3}", item.upper()) for item in shipments
    ):
        raise ValueError("Invalid mapped shipment columns")
    if kind in {"shipments", "snapshot"} and not shipments:
        raise ValueError("Shipment mapping lacks shipment columns")
    mapped_columns = {item for item in (sku, name, article, unit) if item is not None}
    mapped_columns.update(column_name for column_name, _ in months)
    mapped_columns.update(column_name for _, column_name in fields)
    mapped_columns.update(column_name for _, column_name in metrics)
    mapped_columns.update(item.upper() for item in shipments)
    if not mapped_columns.issubset(cited_columns):
        missing = sorted(mapped_columns - cited_columns)
        raise ValueError(f"Mapped columns lack source citations: {missing}")
    return _mapping(
        kind,
        header_end=max(header_row, data_start - 1),
        header_rows=tuple(range(header_row, data_start)),
        sku_col=sku,
        name_col=name,
        article_col=article,
        unit_col=unit,
        month_columns=tuple(months),
        field_columns=fields,
        metric_columns=metrics,
        shipment_columns=tuple(item.upper() for item in shipments),
        labels=_labels(headers),
    )


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


def observations(kind, supplier, cells, row, headers, unit, as_of, mapping=None):
    mapping = mapping or resolve_mapping(headers, supplier)
    header_row = mapping.header_rows[-1] if mapping.header_rows else row
    header = headers.get(header_row, {})
    fields = mapping.fields
    if kind == "movements":
        timestamp = value(cells, fields.get("timestamp", "A"))
        if not isinstance(timestamp, str):
            raise ValueError(f"Expected explicit movement timestamp, row {row}")
        yield (
            "movements",
            {
                "occurred_at": datetime.strptime(timestamp, "%d.%m.%Y %H:%M:%S"),
                "document_number": str(value(cells, fields.get("document_number", "B"))),
                "document_text": value(cells, fields.get("document_text", "C")),
                "unit": unit,
                "warehouse_name": value(cells, fields.get("warehouse", "G")),
                "quantity": number(cells, fields.get("quantity", "H")),
            },
        )
    if kind in ("monthly_sales", "monthly_stock", "snapshot"):
        for column, month in mapping.month_columns:
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
    rule_column = fields.get("quantity_rule")
    if rule_column:
        rule_label = next(
            (
                str(value(cells, rule_column))
                for r, cells in _rows(headers)
                if r <= mapping.header_end
                and any(token in _text(value(cells, rule_column)) for token in ("кратность", "мин разр"))
            ),
            str(value(header, rule_column)),
        )
        yield (
            "quantity_rules",
            {
                "source_column": rule_column,
                "label": rule_label,
                "kind": "minimum_shipment" if supplier == "iek" else "order_multiple",
                "value": number(cells, rule_column),
                "unit": unit,
                "interpretation_confirmed": supplier == "systeme" and "кратность" in rule_label.casefold(),
            },
        )
    if kind in ("shipments", "snapshot"):
        for column in mapping.shipment_columns:
            yield "shipment_lines", {"source_column": column, "quantity": number(cells, column), "unit": unit}
    metrics = {column: metric for metric, column in mapping.metric_columns}
    if kind in ("monthly_stock", "monthly_sales"):
        metrics = {
            column: metric
            for metric, column in mapping.metric_columns
            if metric in {"stock_total", "sales_total"}
        }
    if kind == "snapshot":
        inventory_metrics = {
            "showroom",
            "trading_area",
            "distribution_center",
            "retail",
            "on_hand",
            "reserved",
            "free",
        }
        for metric, column in mapping.metric_columns:
            if metric not in inventory_metrics:
                continue
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
        metrics = {column: metric for column, metric in metrics.items() if metric not in inventory_metrics}
    for column, metric in metrics.items():
        start = end = None
        if kind == "snapshot" and metric in {"sales_total", "sales_average"} and column in {"S", "T"}:
            start, end = date(2024, 1, 1), date(2024, 12, 31)
        # Supplied AP/AQ labels are intentionally not treated as a verified period.
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
