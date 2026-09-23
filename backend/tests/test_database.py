import hashlib
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from replenishment.catalog.models import Product, Supplier, Warehouse
from replenishment.demand.models import MonthlySales, SalesMovement
from replenishment.intake.models import SourceRow, SourceSheet, SourceWorkbook
from replenishment.inventory.models import StockObservation
from replenishment.schema import metadata
from replenishment.supply.models import IncomingShipment, IncomingShipmentLine, QuantityRuleObservation

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated empty PostgreSQL test database")
    assert make_url(url).database.endswith("_test"), "Refusing to migrate a non-test database"
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    assert not inspect(engine).get_table_names(), "Use an empty test database"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "head")
        command.check(config)  # Frozen migration must agree with the models.
        yield engine
        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
        command.upgrade(config, "head")  # Also prove recreation.
        command.check(config)
        command.downgrade(config, "base")
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE alembic_version"))
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture
def db(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


def seed(db):
    supplier = Supplier(code="systeme", name="Systeme Electric")
    warehouse = Warehouse(name="Алматы")
    payload = b"source fixture"
    book = SourceWorkbook(
        sha256=hashlib.sha256(payload).hexdigest(),
        content=payload,
        byte_size=len(payload),
        original_path="fixture.xlsx",
        capture_version="v1",
    )
    db.add_all([supplier, warehouse, book])
    db.flush()
    product = Product(supplier_id=supplier.id, sku="030200745_")
    sheet = SourceSheet(
        workbook_id=book.id,
        name="TDSheet",
        position=0,
        reported_rows=499,
        reported_columns=70,
        layout={"merged_ranges": ["AT1:AW1"]},
    )
    db.add_all([product, sheet])
    db.flush()
    row = SourceRow(
        sheet_id=sheet.id,
        row_number=258,
        cells={
            "C": {"type": "string", "value": "030200745_"},
            "AZ": {"type": "formula", "formula": "=AX258-AY258", "cached_value": "23"},
            "E": {"type": "error", "value": "#N/A"},
            "H": {"type": "number", "value": "0"},
        },
    )
    db.add(row)
    db.flush()
    return supplier, warehouse, book, product, sheet, row


def test_roundtrip_signed_missing_zero_and_uncertain_scope(db):
    supplier, warehouse, book, product, sheet, row = seed(db)
    db.add(
        SalesMovement(
            source_row_id=row.id,
            normalizer_version="v1",
            product_id=product.id,
            warehouse_id=warehouse.id,
            occurred_at=datetime(2023, 7, 20, 16, 15, 38),
            document_number="000123",
            document_text="Расходная накладная",
            unit="шт",
            quantity=Decimal("-10.125"),
        )
    )
    db.add(
        MonthlySales(
            source_row_id=row.id,
            source_column="G",
            normalizer_version="v1",
            product_id=product.id,
            month=date(2024, 1, 1),
            quantity=None,
        )
    )
    db.add(
        StockObservation(
            source_row_id=row.id,
            source_column="AZ",
            normalizer_version="v1",
            product_id=product.id,
            scope_label="Свободный остаток",
            warehouse_id=None,
            as_of=date(2026, 9, 22),
            date_basis="filename",
            metric="free",
            quantity=Decimal(23),
        )
    )
    db.add(
        QuantityRuleObservation(
            source_row_id=row.id,
            source_column="D",
            normalizer_version="v1",
            product_id=product.id,
            label="Кратность",
            kind="order_multiple",
            value=Decimal(0),
            interpretation_confirmed=False,
        )
    )
    db.flush()
    db.expire_all()
    assert db.scalar(select(SalesMovement)).quantity == Decimal("-10.125")
    assert db.scalar(select(SalesMovement)).document_number == "000123"
    assert db.scalar(select(MonthlySales)).quantity is None
    assert db.scalar(select(StockObservation)).warehouse_id is None
    assert db.scalar(select(QuantityRuleObservation)).value == 0
    assert db.get(Product, product.id).sku == "030200745_"
    assert db.get(SourceRow, row.id).cells["E"]["value"] == "#N/A"
    assert "I" not in db.get(SourceRow, row.id).cells
    assert db.get(SourceWorkbook, book.id).content == b"source fixture"


def test_identity_replay_and_foreign_keys(db):
    supplier, warehouse, book, product, sheet, row = seed(db)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(Product(supplier_id=supplier.id, sku=product.sku))
        db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(SourceRow(sheet_id=sheet.id, row_number=258, cells={}))
        db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(SourceRow(sheet_id=uuid4(), row_number=1, cells={}))
        db.flush()
    db.add(
        MonthlySales(
            source_row_id=row.id,
            source_column="G",
            normalizer_version="v1",
            product_id=product.id,
            month=date(2024, 1, 1),
            quantity=Decimal(3),
        )
    )
    db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            MonthlySales(
                source_row_id=row.id,
                source_column="G",
                normalizer_version="v1",
                product_id=product.id,
                month=date(2024, 1, 1),
                quantity=Decimal(4),
            )
        )
        db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            MonthlySales(
                source_row_id=row.id,
                source_column="H",
                normalizer_version="v1",
                product_id=product.id,
                month=date(2024, 1, 2),
                quantity=Decimal(4),
            )
        )
        db.flush()


def test_source_immutability_and_hash_integrity(db):
    _, _, book, _, _, row = seed(db)
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("UPDATE intake_rows SET cells = '{}' WHERE id = :id"), {"id": row.id})
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("DELETE FROM intake_rows WHERE id = :id"), {"id": row.id})
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            SourceWorkbook(
                sha256="0" * 64, content=b"x", byte_size=1, original_path="bad.xlsx", capture_version="v1"
            )
        )
        db.flush()


def test_supplier_mismatch_on_incoming_shipment_is_rejected(db):
    supplier, _, _, product, sheet, row = seed(db)
    other = Supplier(code="iek", name="IEK")
    db.add(other)
    db.flush()
    shipment = IncomingShipment(
        supplier_id=other.id,
        source_sheet_id=sheet.id,
        source_column="BC",
        normalizer_version="v1",
        header="СЭ в пути 24.09",
        date_basis="unknown",
    )
    db.add(shipment)
    db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            IncomingShipmentLine(
                shipment_id=shipment.id,
                supplier_id=supplier.id,
                product_id=product.id,
                source_row_id=row.id,
                source_column="BC",
                normalizer_version="v1",
                quantity=Decimal(120),
            )
        )
        db.flush()


def test_migration_created_all_owned_tables(engine):
    assert set(inspect(engine).get_table_names()) == set(metadata.tables) | {"alembic_version"}
