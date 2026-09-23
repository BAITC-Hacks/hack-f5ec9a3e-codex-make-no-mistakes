from datetime import date
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from replenishment.kernel.db import Base, Id, Number


class QuantityRuleObservation(Base):
    __tablename__ = "supply_quantity_rules"
    __table_args__ = (
        UniqueConstraint("source_row_id", "source_column", "normalizer_version"),
        CheckConstraint("kind IN ('minimum_shipment', 'order_multiple', 'unconfirmed')", name="kind"),
    )
    id: Mapped[Id]
    source_row_id: Mapped[UUID] = mapped_column(ForeignKey("intake_rows.id"))
    source_column: Mapped[str]
    normalizer_version: Mapped[str]
    product_id: Mapped[UUID] = mapped_column(ForeignKey("catalog_products.id"), index=True)
    label: Mapped[str]
    kind: Mapped[str]
    value: Mapped[Number | None]  # Preserve reported zero; do not replace errors with one.
    unit: Mapped[str | None]
    interpretation_confirmed: Mapped[bool] = mapped_column(default=False)


class IncomingShipment(Base):
    __tablename__ = "supply_shipments"
    __table_args__ = (
        UniqueConstraint("source_sheet_id", "source_column", "normalizer_version"),
        UniqueConstraint("id", "supplier_id"),
        CheckConstraint("date_basis IN ('explicit', 'assumed_year', 'unknown')", name="date_basis"),
    )
    id: Mapped[Id]
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("catalog_suppliers.id"))
    source_sheet_id: Mapped[UUID] = mapped_column(ForeignKey("intake_sheets.id"))
    source_column: Mapped[str]
    normalizer_version: Mapped[str]
    header: Mapped[str]
    document_number: Mapped[str | None]
    ordered_on: Mapped[date | None]
    expected_on: Mapped[date | None]
    date_basis: Mapped[str]
    warehouse_id: Mapped[UUID | None] = mapped_column(ForeignKey("catalog_warehouses.id"))


class IncomingShipmentLine(Base):
    __tablename__ = "supply_shipment_lines"
    __table_args__ = (
        UniqueConstraint("source_row_id", "source_column", "normalizer_version"),
        ForeignKeyConstraint(
            ["product_id", "supplier_id"], ["catalog_products.id", "catalog_products.supplier_id"]
        ),
        ForeignKeyConstraint(
            ["shipment_id", "supplier_id"], ["supply_shipments.id", "supply_shipments.supplier_id"]
        ),
    )
    id: Mapped[Id]
    shipment_id: Mapped[UUID] = mapped_column(index=True)
    supplier_id: Mapped[UUID]
    product_id: Mapped[UUID] = mapped_column(index=True)
    source_row_id: Mapped[UUID] = mapped_column(ForeignKey("intake_rows.id"))
    source_column: Mapped[str]
    normalizer_version: Mapped[str]
    quantity: Mapped[Number | None]
    unit: Mapped[str | None]
