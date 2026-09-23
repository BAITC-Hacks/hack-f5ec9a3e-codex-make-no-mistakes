"""Independent source-to-planning checks against an empty, isolated test database."""

import hashlib
import os
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from replenishment.api.app import create_app
from replenishment.api.planning_sources import SourceSelection
from replenishment.planning.calculator import calculate
from replenishment.planning.models import PlanningRequest
from replenishment.planning_sources import prepare_source_input
from replenishment.schema import metadata

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def engine():
    url = os.environ.get("SOURCE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set SOURCE_TEST_DATABASE_URL to an empty replenishment_sources_test database")
    engine = create_engine(url)
    if engine.url.database != "replenishment_sources_test" or inspect(engine).get_table_names():
        engine.dispose()
        raise RuntimeError("Source tests require an empty replenishment_sources_test database")
    metadata.create_all(engine)
    try:
        yield engine
    finally:
        metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def source(engine):
    with engine.connect() as connection, connection.begin() as transaction:
        ids = {key: uuid4() for key in ("supplier", "product", "warehouse", "book", "sheet")}

        def add(table, **values):
            connection.execute(metadata.tables[table].insert().values(**values))

        add("catalog_suppliers", id=ids["supplier"], code="fixture", name="Systeme fixture")
        add("catalog_products", id=ids["product"], supplier_id=ids["supplier"], sku="001_")
        add("catalog_warehouses", id=ids["warehouse"], name="Алматы")
        content = b"independent planning source fixture"
        add("intake_workbooks", id=ids["book"], sha256=hashlib.sha256(content).hexdigest(),
            content=content, byte_size=len(content), original_path="fixture.xlsx", capture_version="v1")
        add("intake_sheets", id=ids["sheet"], workbook_id=ids["book"], name="source", position=0,
            reported_rows=10, reported_columns=8)
        for index in range(1, 7):
            source_id = uuid4()
            ids[f"row{index}"] = source_id
            add("intake_rows", id=source_id, sheet_id=ids["sheet"], row_number=index, cells={})
        for index, quantity, when in (
            (1, "10", datetime(2026, 9, 20, 10)),
            (2, "5", datetime(2026, 9, 20, 11)),
            (3, "-4", datetime(2026, 9, 20, 12)),
            (4, None, datetime(2026, 9, 20, 13)),
            (5, "999", datetime(2026, 9, 23, 10)),
        ):
            add("demand_movements", source_row_id=ids[f"row{index}"], normalizer_version="v1",
                product_id=ids["product"], warehouse_id=ids["warehouse"], occurred_at=when,
                document_number="same-document", document_text="Расходная накладная", unit="шт",
                quantity=Decimal(quantity) if quantity is not None else None)
        add("inventory_observations", product_id=ids["product"], source_row_id=ids["row6"],
            source_column="AZ", normalizer_version="v1", scope_label="Свободный остаток", metric="free",
            quantity=Decimal(23), as_of=date(2026, 9, 22), date_basis="filename")
        request = SourceSelection(product_ids=[ids["product"]], planning_date=date(2026, 9, 23),
                                  warehouse="Алматы")
        yield connection, ids, add, request
        transaction.rollback()


def test_preserves_uncertainty_and_does_not_mix_future_signed_or_missing_sales(source):
    connection, ids, _, request = source
    prepared = prepare_source_input(connection, metadata, request)
    row = prepared["input"]["rows"][0]
    assert row["sku"] == "001_"
    assert row["sales"] == [{"day": "2026-09-20", "quantity": "15.000000000000",
                             "document": "same-document | Расходная накладная", "customer_id": None}]
    assert Decimal(row["free_stock"]) == 23
    assert row["stock_as_of"] == "2026-09-22"
    assert not row["stock_scope_confirmed"]
    assert row["stock_per_purchase_unit"] is None
    assert not row["incoming_complete"] and not row["constraints_confirmed"]
    assert any(ref["workbook_id"] == str(ids["book"]) for ref in row["sources"])
    assert any("negative_unresolved" in note for note in row["notes"])
    result = calculate(PlanningRequest.model_validate(prepared["input"]))
    assert result.rows[0].status == "needs_input"
    assert result.rows[0].recommended_quantity is None
    assert len(prepared["usage"]) == 9


def test_requires_version_selection_instead_of_doubling_history(source):
    connection, ids, add, request = source
    add("demand_movements", source_row_id=ids["row1"], normalizer_version="v2",
        product_id=ids["product"], warehouse_id=ids["warehouse"], occurred_at=datetime(2026, 9, 20),
        document_number="same-document", document_text="Расходная накладная", unit="шт", quantity=100)
    with pytest.raises(ValueError, match="Multiple normalizer versions"):
        prepare_source_input(connection, metadata, request)
    selection = request.model_copy(update={"normalizer_version": "v1"})
    prepared = prepare_source_input(connection, metadata, selection)
    assert sum(Decimal(r["quantity"]) for r in prepared["input"]["rows"][0]["sales"]) == 15


def test_explicit_history_window_excludes_later_sales_and_rejects_future_history(source):
    connection, ids, _, request = source
    selection = SourceSelection(product_ids=[ids["product"]], planning_date=request.planning_date,
                                warehouse="Алматы", history_start=date(2026, 9, 1),
                                history_end=date(2026, 9, 19))
    prepared = prepare_source_input(connection, metadata, selection)
    assert prepared["input"]["rows"][0]["sales"] == []
    with pytest.raises(ValueError, match="strictly before"):
        SourceSelection(product_ids=[ids["product"]], planning_date=request.planning_date,
                        warehouse="Алматы", history_start=date(2026, 9, 1),
                        history_end=request.planning_date)


def test_document_text_is_part_of_identity_for_bulk_analysis(source):
    connection, ids, add, request = source
    add("demand_movements", source_row_id=ids["row6"], normalizer_version="v1",
        product_id=ids["product"], warehouse_id=ids["warehouse"], occurred_at=datetime(2026, 9, 20),
        document_number="same-document", document_text="Расходная накладная другой документ",
        unit="шт", quantity=25)
    row = prepare_source_input(connection, metadata, request)["input"]["rows"][0]
    assert len(row["sales"]) == 2
    assert sorted(Decimal(sale["quantity"]) for sale in row["sales"]) == [15, 25]


def test_wrong_warehouse_never_relabels_sales(source):
    connection, _, _, request = source
    prepared = prepare_source_input(connection, metadata, request.model_copy(update={"warehouse": "Астана"}))
    row = prepared["input"]["rows"][0]
    assert row["sales"] == []
    assert row["history_start"] is None
    assert row["stock_unit"] == "unknown"
    assert not row["stock_scope_confirmed"]


def test_human_warehouse_input_is_trimmed_before_source_selection(source):
    connection, ids, _, request = source
    selection = SourceSelection(product_ids=[ids["product"]], planning_date=request.planning_date,
                                warehouse=" Алматы ")
    prepared = prepare_source_input(connection, metadata, selection)
    assert prepared["input"]["rows"][0]["warehouse"] == "Алматы"
    assert len(prepared["input"]["rows"][0]["sales"]) == 1


def test_duplicate_product_selection_is_rejected_before_queries():
    product = uuid4()
    with pytest.raises(ValueError, match="Identifiers must be unique"):
        SourceSelection(product_ids=[product, product], planning_date=date(2026, 9, 23), warehouse="Алматы")


def test_composed_application_calculation_save_approve_export_and_invalidation(engine):
    with TestClient(create_app(engine)) as client:
        assert client.get("/api/v1/tables").status_code == 200
        cases = client.get("/api/v1/planning/demo-cases").json()
        scenario_input = next(case["input"] for case in cases if case["id"] == "baseline")
        preview = client.post("/api/v1/planning/calculate", json=scenario_input)
        assert preview.status_code == 200
        saved = client.post("/api/v1/scenarios", json={"name": "Composed app", "input": scenario_input})
        assert saved.status_code == 201, saved.text
        saved = saved.json()
        path = f"/api/v1/scenarios/{saved['id']}"
        assert saved["result"] == preview.json()
        assert client.get(path + "/export?expected_revision=1").status_code == 409
        approved = client.post(path + "/approve", json={
            "expected_revision": 1, "approved_by": "Backend acceptance", "acknowledge_scenario": True,
        })
        assert approved.status_code == 200, approved.text
        exported = client.get(path + "/export?expected_revision=1")
        assert exported.status_code == 200
        assert "approved_quantity" in exported.text
        updated = client.put(path, json={"expected_revision": 1, "name": "Changed revision",
                                         "input": scenario_input, "overrides": []})
        assert updated.status_code == 200
        assert updated.json()["approved_revision"] is None
        assert client.get(path + "/export?expected_revision=2").status_code == 409
        source = client.post("/api/v1/planning/source-input", json={
            "product_ids": [str(uuid4())], "planning_date": "2026-09-23", "warehouse": "Алматы",
        })
        assert source.status_code == 422
        assert "products do not exist" in source.json()["detail"]
