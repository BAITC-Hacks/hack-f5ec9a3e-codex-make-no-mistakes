from datetime import date
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from replenishment.kernel.db import Base, Id, Number


class MonthlyStock(Base):
    __tablename__ = "inventory_monthly_stock"
    __table_args__ = (
        UniqueConstraint("source_row_id", "source_column", "normalizer_version"),
        CheckConstraint("metric IN ('opening_stock', 'stock_unspecified')", name="metric"),
        CheckConstraint("extract(day FROM month) = 1", name="month_start"),
    )
    id: Mapped[Id]
    source_row_id: Mapped[UUID] = mapped_column(ForeignKey("intake_rows.id"))
    source_column: Mapped[str]
    normalizer_version: Mapped[str]
    product_id: Mapped[UUID] = mapped_column(ForeignKey("catalog_products.id"), index=True)
    warehouse_id: Mapped[UUID | None] = mapped_column(ForeignKey("catalog_warehouses.id"))
    month: Mapped[date] = mapped_column(index=True)
    metric: Mapped[str]
    quantity: Mapped[Number | None]
    unit: Mapped[str | None]


class StockObservation(Base):
    __tablename__ = "inventory_observations"
    __table_args__ = (
        UniqueConstraint("source_row_id", "source_column", "normalizer_version"),
        CheckConstraint(
            "metric IN ('on_hand', 'reserved', 'free', 'showroom', 'trading_area', "
            "'distribution_center', 'retail')",
            name="metric",
        ),
        CheckConstraint("date_basis IN ('explicit', 'filename', 'assumed', 'unknown')", name="date_basis"),
    )
    id: Mapped[Id]
    source_row_id: Mapped[UUID] = mapped_column(ForeignKey("intake_rows.id"))
    source_column: Mapped[str]
    normalizer_version: Mapped[str]
    product_id: Mapped[UUID] = mapped_column(ForeignKey("catalog_products.id"), index=True)
    warehouse_id: Mapped[UUID | None] = mapped_column(ForeignKey("catalog_warehouses.id"))
    scope_label: Mapped[str]  # Verbatim heading, not a guessed canonical warehouse.
    as_of: Mapped[date | None]
    date_basis: Mapped[str]
    metric: Mapped[str]
    quantity: Mapped[Number | None]
    unit: Mapped[str | None]
