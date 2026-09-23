import csv
import hashlib
from io import BytesIO, StringIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_excel_import import import_engine  # noqa: F401 -- shared isolated PostgreSQL fixture

from replenishment.api.app import create_app
from replenishment.api.uploads import upload_sources
from replenishment.intake.adapters.csv import CSV_COLUMNS, CsvWorkbook, csv_observation


def csv_content(quantity="12.50"):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)
    writer.writerows([
        ["monthly_sales", "00123", "Product", "2026-08-01", quantity, "шт", "Алматы", "", ""],
        ["monthly_stock", "00123", "Product", "2026-09-01", "0", "шт", "Алматы", "", ""],
        ["incoming", "00123", "Product", "2026-10-01", "5", "шт", "Алматы", "PO-1", ""],
        ["movements", "00123", "Product", "2026-08-02", "3", "шт", "Алматы", "001",
         "Расходная накладная"],
    ])
    return output.getvalue().encode("utf-8-sig")


def test_csv_preserves_codes_and_validates_required_numbers_dates():
    workbook = CsvWorkbook(csv_content())
    rows = dict(workbook.rows(workbook.sheets[0]))
    assert rows[2]["B"]["value"] == "00123"
    assert str(csv_observation(rows[2], 2)[1]["quantity"]) == "12.500000000000"
    assert csv_observation(rows[3], 3)[1]["quantity"] == 0
    assert csv_observation(rows[4], 4)[0] == "shipment_lines"
    assert csv_observation(rows[5], 5)[1]["document_text"] == "Расходная накладная"
    for quantity in ("", "NaN", "oops"):
        book = CsvWorkbook(csv_content(quantity))
        with pytest.raises(ValueError):
            csv_observation(dict(book.rows(book.sheets[0]))[2], 2)
    rows[2]["D"]["value"] = "2026-08-02"
    with pytest.raises(ValueError, match="first day"):
        csv_observation(rows[2], 2)


def test_upload_transport_rejects_empty_and_unsafe_archives_and_reuses_importer(monkeypatch):
    calls = []

    def importer(engine, path, supplier, *, content):
        calls.append((path, supplier, content))
        return {"path": path, "status": "imported", "workbook_id": "test"}

    monkeypatch.setattr("replenishment.api.uploads.import_workbook", importer)
    client = TestClient(create_app(object()))
    assert client.post("/api/v1/sources/upload?filename=x.csv", content=b"").status_code == 422
    assert client.post("/api/v1/sources/upload?filename=x.exe", content=b"bad").status_code == 422
    assert client.post("/api/v1/sources/upload?filename=x.csv&supplier=bad", content=b"x").status_code == 422
    archive = BytesIO()
    with ZipFile(archive, "w") as output:
        output.writestr("IEK/Продажи.csv", csv_content())
    response = client.post("/api/v1/sources/upload?filename=IEK.zip", content=archive.getvalue())
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "imported"
    assert calls[0][0] == "IEK.zip/IEK/Продажи.csv"
    assert calls[0][2] == csv_content()
    archive = BytesIO()
    with ZipFile(archive, "w") as output:
        output.writestr("../IEK.csv", csv_content())
    assert client.post("/api/v1/sources/upload?filename=x.zip", content=archive.getvalue()).status_code == 422
    assert len(calls) == 1


@pytest.mark.postgres
def test_csv_upload_persists_domains_exports_and_replays_atomically(import_engine):  # noqa: F811
    client = TestClient(create_app(import_engine))
    url = "/api/v1/sources/upload?filename=IEK-canonical.csv"
    sku = "00123_" + uuid4().hex
    content = csv_content().replace(b"00123", sku.encode())
    result = client.post(url, content=content).json()["results"][0]
    assert result["status"] == "imported"
    workbook_id = result["workbook_id"]
    for table, count in [("monthly-sales", 1), ("monthly-stock", 1), ("shipment-lines", 1), ("movements", 1)]:
        page = client.get(f"/api/v1/tables/{table}?workbook_id={workbook_id}").json()
        assert page["total"] == count
        assert page["items"][0]["sku"] == sku
    product_id = page["items"][0]["product_id"]
    prepared = client.post("/api/v1/planning/source-input", json={
        "product_ids": [product_id], "planning_date": "2026-09-01", "warehouse": "Алматы",
        "workbook_ids": [workbook_id], "normalizer_version": "v1",
    })
    assert prepared.status_code == 200
    planning_row = prepared.json()["input"]["rows"][0]
    assert planning_row["sales"][0]["quantity"] == "3.000000000000"
    assert planning_row["incoming"][0]["quantity"] == "5.000000000000"
    exported = client.get(f"/api/v1/sources/export/monthly-sales.csv?workbook_id={workbook_id}")
    assert exported.status_code == 200 and "00123" in exported.text and "12.500000000000" in exported.text
    filtered = client.get(f"/api/v1/sources/export/monthly-sales.csv?workbook_id={workbook_id}&q=absent-sku")
    assert filtered.status_code == 200 and len(filtered.text.splitlines()) == 1
    invalid_filter = client.get(f"/api/v1/sources/export/findings.csv?supplier_id={workbook_id}")
    assert invalid_filter.status_code == 422
    assert client.post(url, content=content).json()["results"][0]["status"] == "skipped"
    bad = content.replace(b",3,", b",invalid,")
    assert upload_sources(import_engine, bad, "IEK-invalid.csv", None)["results"][0]["status"] == "failed"
    with import_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM intake_workbooks WHERE sha256=:sha"),
                                 {"sha": hashlib.sha256(bad).hexdigest()}) == 0
