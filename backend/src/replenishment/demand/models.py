from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from replenishment.kernel.db import Base, Id, Number


class SalesMovement(Base):
    __tablename__ = "demand_movements"
    __table_args__ = (UniqueConstraint("source_row_id", "normalizer_version"),)
    id: Mapped[Id]
    source_row_id: Mapped[UUID] = mapped_column(ForeignKey("intake_rows.id"))
    normalizer_version: Mapped[str]
    product_id: Mapped[UUID] = mapped_column(ForeignKey("catalog_products.id"), index=True)
    warehouse_id: Mapped[UUID] = mapped_column(ForeignKey("catalog_warehouses.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    # Excel timestamps are local/unspecified, never silently treated as UTC.
    document_number: Mapped[str]
    document_text: Mapped[str]
    unit: Mapped[str]
    quantity: Mapped[Number | None]  # Signed source movement, NOT cleaned demand.


class MonthlySales(Base):
    __tablename__ = "demand_monthly_sales"
    __table_args__ = (
        UniqueConstraint("source_row_id", "source_column", "normalizer_version"),
        CheckConstraint("extract(day FROM month) = 1", name="month_start"),
    )
    id: Mapped[Id]
    source_row_id: Mapped[UUID] = mapped_column(ForeignKey("intake_rows.id"))
    source_column: Mapped[str]
    normalizer_version: Mapped[str]
    product_id: Mapped[UUID] = mapped_column(ForeignKey("catalog_products.id"), index=True)
    warehouse_id: Mapped[UUID | None] = mapped_column(ForeignKey("catalog_warehouses.id"))
    month: Mapped[date] = mapped_column(index=True)
    quantity: Mapped[Number | None]
    unit: Mapped[str | None]
    is_complete_period: Mapped[bool | None]  # NULL = unconfirmed, not a full month by default.


class ReportMetric(Base):
    __tablename__ = "demand_report_metrics"
    __table_args__ = (
        UniqueConstraint("source_row_id", "source_column", "normalizer_version"),
        CheckConstraint(
            "metric IN ('sales_total', 'sales_average', 'growth_change', 'seasonality_change', "
            "'cost_unspecified', 'coverage_unspecified', 'planned_order', "
            "'weight_unspecified', 'stock_total')",
            name="metric",
        ),
    )
    id: Mapped[Id]
    source_row_id: Mapped[UUID] = mapped_column(ForeignKey("intake_rows.id"))
    source_column: Mapped[str]
    normalizer_version: Mapped[str]
    product_id: Mapped[UUID] = mapped_column(ForeignKey("catalog_products.id"), index=True)
    metric: Mapped[str]
    label: Mapped[str]
    value: Mapped[Number | None]
    unit: Mapped[str | None]
    period_start: Mapped[date | None]
    period_end: Mapped[date | None]
    # Supplied report outputs, not trusted recalculations or independent growth forecasts.


class SeasonalityObservation(Base):
    __tablename__ = "demand_seasonality_observations"
    __table_args__ = (
        UniqueConstraint("source_row_id", "source_column", "normalizer_version"),
        CheckConstraint("month IS NULL OR month BETWEEN 1 AND 12", name="month"),
        CheckConstraint("basis IN ('reported', 'derived', 'forecast', 'unknown')", name="basis"),
    )
    id: Mapped[Id]
    source_row_id: Mapped[UUID] = mapped_column(ForeignKey("intake_rows.id"))
    source_column: Mapped[str]
    normalizer_version: Mapped[str]
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("catalog_suppliers.id"))
    year: Mapped[int | None]
    month: Mapped[int | None]
    metric: Mapped[str]  # report_total, average, normalized_coefficient, adjustment, etc.
    label: Mapped[str]
    value: Mapped[Number | None]
    unit: Mapped[str | None]
    basis: Mapped[str]
    # Supplier aggregates, never implicitly applied to each SKU. Duplicate sheets remain separate evidence.
