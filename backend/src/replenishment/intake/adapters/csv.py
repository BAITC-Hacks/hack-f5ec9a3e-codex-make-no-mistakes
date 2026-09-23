"""Explicit UTF-8 CSV contract; identifiers remain text and original bytes stay evidence."""

import csv
from datetime import date, datetime
from io import StringIO

from openpyxl.utils.cell import get_column_letter

from .normalization import number, value
from .xlsx import Sheet

CSV_COLUMNS = ["record_type", "sku", "name", "date", "quantity", "unit", "warehouse",
               "document_number", "document_text"]
CSV_TYPES = {"monthly_sales", "monthly_stock", "movements", "incoming"}


class CsvWorkbook:
    def __init__(self, content):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("CSV must use UTF-8 encoding") from error
        delimiter = ";" if text and ";" in text.splitlines()[0] else ","
        try:
            self.records = list(csv.reader(StringIO(text), delimiter=delimiter, strict=True))
        except csv.Error as error:
            raise ValueError(f"Invalid CSV: {error}") from error
        if not self.records or self.records[0] != CSV_COLUMNS:
            raise ValueError("CSV header must be: " + ",".join(CSV_COLUMNS))
        if len(self.records) < 2:
            raise ValueError("CSV contains no data rows")
        self.sheets = [Sheet("CSV", "", 0, len(self.records), len(CSV_COLUMNS), {})]

    def rows(self, sheet):
        for row, record in enumerate(self.records, 1):
            if not any(record):
                continue
            if len(record) != len(CSV_COLUMNS):
                raise ValueError(f"CSV row {row}: expected {len(CSV_COLUMNS)} columns")
            if row > 1 and (record[0] not in CSV_TYPES or not record[1].strip()):
                raise ValueError(f"CSV row {row}: unsupported record_type or missing SKU")
            yield row, {get_column_letter(i): {"type": "n" if row > 1 and i == 5 else "s",
                                              "value": item, "number_format": "General"}
                        for i, item in enumerate(record, 1) if item != ""}

    def close(self):
        pass


def csv_observation(cells, row):
    kind = value(cells, "A")
    quantity = number(cells, "E")
    if quantity is None:
        raise ValueError(f"CSV row {row}: quantity is required (use 0 for zero)")
    try:
        when = date.fromisoformat(value(cells, "D"))
    except (ValueError, TypeError) as error:
        raise ValueError(f"CSV row {row}: date must be YYYY-MM-DD") from error
    item = {"quantity": quantity, "unit": value(cells, "F"), "warehouse_name": value(cells, "G")}
    if kind == "movements":
        if not all(value(cells, col) for col in ("F", "G", "H", "I")):
            raise ValueError(f"CSV row {row}: movements require unit, warehouse and document fields")
        item.update(occurred_at=datetime.combine(when, datetime.min.time()),
                    document_number=value(cells, "H"), document_text=value(cells, "I"))
    else:
        item["source_column"] = "E"
        if kind == "incoming":
            if quantity < 0:
                raise ValueError(f"CSV row {row}: incoming quantity cannot be negative")
            item.update(expected_on=when, document_number=value(cells, "H"))
            kind = "shipment_lines"
        else:
            if when.day != 1:
                raise ValueError(f"CSV row {row}: monthly date must be first day of month")
            item["month"] = when
            if kind == "monthly_sales":
                item["is_complete_period"] = None
            else:
                item["metric"] = "stock_unspecified"
    return kind, item
