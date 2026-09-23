from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

from replenishment.cli.audit_data import compare, expected_sheet, xml_numbers


def test_audit_detects_value_identity_missing_and_null_corruption():
    original = {(2, "H", "001_", ""): Decimal("7"), (3, "H", "002_", ""): None}
    assert compare(original, dict(original))["passed"]
    for changed in (
        {(2, "H", "001_", ""): Decimal("8"), (3, "H", "002_", ""): None},
        {(2, "H", "999_", ""): Decimal("7"), (3, "H", "002_", ""): None},
        {(2, "H", "001_", ""): Decimal("7")},
        {(2, "H", "001_", ""): Decimal("7"), (3, "H", "002_", ""): Decimal("0")},
    ):
        assert not compare(original, changed)["passed"]


def test_audit_sign_and_integer_checks_are_not_hidden_by_tolerance():
    key = (1, "A", "sku", "")
    assert not compare({key: Decimal("0")}, {key: Decimal("-0.000000000001")})["passed"]
    assert not compare({key: Decimal("1")}, {key: Decimal("1.000000000001")})["passed"]
    assert not compare({key: Decimal("0.000000000001")}, {key: Decimal("-0.000000000001")})["passed"]
    assert compare({key: Decimal("0.3333333333333333")}, {key: Decimal("0.333333333333")})["passed"]


def test_independent_source_reader_preserves_error_blank_zero_and_duplicate_rows():
    book = Workbook()
    sheet = book.active
    sheet.title = "Лист7"
    sheet.append(["№", "Код 1с", "Артикул", "Имя", "MOQ"])
    sheet.append([1, "001_", "A", "Name", 0])
    sheet.append([2, "001_", "A", "Name", "#N/A"])
    sheet.append([3, "002_", "B", "Name", None])
    expected, raw, products, warnings, kind = expected_sheet(Path("IEK/MOQ.xlsx"), sheet, sheet)
    assert kind == "moq"
    assert raw == {1, 2, 3, 4}
    assert products == {2: "001_", 3: "001_", 4: "002_"}
    assert list(expected["supply_quantity_rules"].values()) == [Decimal(0), None, None]
    assert warnings["excel_errors"] == 1
    assert warnings["duplicate_sku_rows"] == 1


def test_seasonal_xml_numbers_keep_fraction_below_binary_float_resolution():
    xml = b"""<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <sheetData><row r="4"><c r="N4"><v>2445420373.0700002</v></c>
      <c r="B4"><v>0.33333333333333333</v></c><c r="C4" t="e"><v>#N/A</v></c>
      </row></sheetData></worksheet>"""
    numbers = xml_numbers(xml)
    assert numbers["N4"] == Decimal("2445420373.0700002")
    assert "C4" not in numbers
    assert compare({(4, "N", "", ""): numbers["N4"]}, {(4, "N", "", ""): Decimal("2445420373.070000200000")})[
        "passed"
    ]
    assert compare({(4, "B", "", ""): numbers["B4"]}, {(4, "B", "", ""): Decimal("0.333333333333")})["passed"]
