"""Read API regression against an explicitly isolated PostgreSQL database."""

import hashlib
import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from replenishment.api.app import create_app
from replenishment.schema import metadata


@pytest.fixture(scope="module")
def api():
    url = os.environ.get("API_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set API_TEST_DATABASE_URL to a dedicated empty PostgreSQL test database")
    engine = create_engine(url)
    if engine.url.database != "replenishment_api_test":
        raise RuntimeError("API tests require dedicated replenishment_api_test database")
    with engine.connect() as connection:
        existing = connection.execute(text(
            "SELECT schemaname, tablename FROM pg_tables "
            "WHERE schemaname NOT IN ('pg_catalog', 'information_schema')"
        )).all()
    if existing:
        engine.dispose()
        raise RuntimeError(f"API test database must be empty; found {existing}")
    try:
        metadata.create_all(engine)
        ids = {key: uuid4() for key in (
            "supplier", "other", "product", "other_product", "book", "sheet", "row"
        )}
        with engine.begin() as connection:
            def add(table, **values):
                connection.execute(metadata.tables[table].insert().values(**values))
            for key in ("supplier", "other"):
                add("catalog_suppliers", id=ids[key], code=str(ids[key]), name=key)
            for key, supplier in (("product", "supplier"), ("other_product", "other")):
                add("catalog_products", id=ids[key], supplier_id=ids[supplier], sku="001_%")
            content = str(ids["book"]).encode()
            add("intake_workbooks", id=ids["book"], sha256=hashlib.sha256(content).hexdigest(),
                original_path="source.xlsx", byte_size=len(content), content=content, capture_version="test")
            add("intake_sheets", id=ids["sheet"], workbook_id=ids["book"], name="Sheet", position=0,
                reported_rows=2, reported_columns=2)
            add("intake_rows", id=ids["row"], sheet_id=ids["sheet"], row_number=2,
                cells={"A": {"type": "f", "formula": "=1/3", "cached_value": "0.3333333333333333"},
                       "B": {"type": "e", "value": "#N/A"}})
            for i in range(3):
                add("catalog_product_observations", product_id=ids["product"], source_row_id=ids["row"],
                    normalizer_version=f"api-test-{i}", name="Cable",
                    supplier_article="A-1", category_code="7")
            add("catalog_product_observations", product_id=ids["other_product"], source_row_id=ids["row"],
                normalizer_version="api-test-other", name="Other")
            for column, quantity in (("A", Decimal("0.333333333333")), ("B", None), ("C", Decimal("0"))):
                add("demand_monthly_sales", product_id=ids["product"], source_row_id=ids["row"],
                    normalizer_version="api-test", source_column=column,
                    month=date(2026, 9, 1), quantity=quantity)
        with TestClient(create_app(engine)) as client:
            yield client, ids
    finally:
        try:
            metadata.drop_all(engine)
        finally:
            engine.dispose()


def test_descriptors_and_validation(api):
    client, _ = api
    descriptors = client.get("/api/v1/tables").json()
    assert len(descriptors) == 20
    for descriptor in descriptors:
        assert client.get(f"/api/v1/tables/{descriptor['key']}").status_code == 200
    assert "content" not in [col["key"] for item in descriptors for col in item["columns"]]
    for query in ("page=0", "page_size=201", "sort=content", "direction=sideways",
                  "supplier_id=bad", "warehouse_id=bad", "sort=id;DROP TABLE catalog_products"):
        assert client.get(f"/api/v1/products?{query}").status_code == 422
    assert client.get("/api/v1/tables/no-such-table").status_code == 404
    assert client.get("/api/v1/suppliers?normalizer_version=v1").status_code == 422
    assert client.get(f"/api/v1/source-rows/{uuid4()}").status_code == 404


def test_paging_literal_search_and_supplier_isolation(api):
    client, ids = api
    params = {"supplier_id": str(ids["supplier"]), "sort": "name", "page_size": 2, "q": "001_%"}
    first = client.get("/api/v1/products", params=params).json()
    second = client.get("/api/v1/products", params={**params, "page": 2}).json()
    assert first["total"] == second["total"] == 3
    assert len({row["id"] for row in first["items"] + second["items"]}) == 3
    assert all(row["supplier_id"] == str(ids["supplier"]) for row in first["items"])
    assert first == client.get("/api/v1/products", params=params).json()
    filtered = client.get("/api/v1/products", params={**params, "normalizer_version": "api-test-1",
                                                    "workbook_id": str(ids["book"])}).json()
    assert filtered["total"] == 1
    catalog = client.get("/api/v1/catalog", params={"supplier_id": str(ids["supplier"])}).json()
    assert catalog["total"] == 1
    assert catalog["items"][0]["product_id"] == str(ids["product"])
    assert catalog["items"][0]["id"] == str(ids["product"])
    assert "name" not in catalog["items"][0]
    assert client.get("/api/v1/products?q=%27%20OR%201=1--").json()["total"] == 0


def test_precision_null_and_provenance(api):
    client, ids = api
    response = client.get("/api/v1/monthly-sales", params={"product_id": str(ids["product"]),
                                                         "sort": "source_column", "warehouse_id": "unknown"})
    assert response.status_code == 200
    rows = response.json()["items"]
    assert [row["quantity"] for row in rows] == ["0.333333333333", None, "0.000000000000"]
    assert all(row["warehouse_id"] is None and row["warehouse_name"] is None for row in rows)
    descending = client.get("/api/v1/monthly-sales", params={"product_id": str(ids["product"]),
                            "sort": "source_column", "direction": "desc"}).json()["items"]
    assert [row["source_column"] for row in descending] == ["C", "B", "A"]
    assert rows[0]["row_number"] == 2
    assert rows[0]["original_path"] == "source.xlsx"
    detail = client.get(f"/api/v1/source-rows/{rows[0]['source_row_id']}").json()
    assert detail["cells"]["A"]["formula"] == "=1/3"
    assert detail["cells"]["B"]["value"] == "#N/A"
    assert "C" not in detail["cells"]


def test_database_errors_do_not_leak_credentials(monkeypatch):
    engine = create_engine("postgresql+psycopg://user:secret@localhost/unavailable")

    def unavailable():
        raise OperationalError("secret database URL", {}, Exception("secret"))

    monkeypatch.setattr(engine, "connect", unavailable)
    with TestClient(create_app(engine)) as client:
        for path in ("health", "products", f"source-rows/{uuid4()}"):
            response = client.get(f"/api/v1/{path}")
            assert response.status_code == 503
            assert response.json() == {"detail": "Database unavailable"}
        response = client.post("/api/v2/calculation/runs", json={
            "planning_date": "2026-09-22",
            "source_selection": [{"table": "demand_monthly_sales", "sha256": "a" * 64,
                                  "normalizer_version": "v2.3"}],
        })
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}
    engine.dispose()


def test_calculation_request_validation_before_database_access(monkeypatch):
    engine = create_engine("postgresql+psycopg://user:secret@localhost/unavailable")

    def unexpected_connection():
        pytest.fail("Invalid calculation request must not access the database")

    monkeypatch.setattr(engine, "connect", unexpected_connection)
    source = {"table": "demand_monthly_sales", "sha256": "a" * 64, "normalizer_version": "v2.3"}
    valid = {"planning_date": "2026-09-22", "source_selection": [source]}
    invalid = [
        {}, {**valid, "source_selection": []}, {**valid, "planning_date": "not-a-date"},
        {**valid, "planning_date": "2099-12-01"}, {**valid, "supplier": "unknown"},
        {**valid, "rerun": "false"}, {**valid, "llm_config": "/private/config.json"},
        *({**valid, "source_selection": [{**source, **override}]} for override in (
            {"sha256": "*"}, {"normalizer_version": ""}, {"table": "calculation_runs"},
            {"unexpected": True},
        )),
    ]
    try:
        with TestClient(create_app(engine)) as client:
            for body in invalid:
                response = client.post("/api/v2/calculation/runs", json=body)
                assert response.status_code == 422, response.text
    finally:
        engine.dispose()
