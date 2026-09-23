from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from replenishment.kernel.db import Base, Id


class Supplier(Base):
    __tablename__ = "catalog_suppliers"
    id: Mapped[Id]
    code: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]


class Product(Base):
    __tablename__ = "catalog_products"
    __table_args__ = (
        UniqueConstraint("supplier_id", "sku"),
        UniqueConstraint("id", "supplier_id"),
        CheckConstraint("length(sku) > 0", name="nonempty_sku"),
    )
    id: Mapped[Id]
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("catalog_suppliers.id"))
    sku: Mapped[str]  # Exact 1C code, including leading zeros, Cyrillic and underscores.


class ProductObservation(Base):
    __tablename__ = "catalog_product_observations"
    __table_args__ = (UniqueConstraint("source_row_id", "normalizer_version"),)
    id: Mapped[Id]
    product_id: Mapped[UUID] = mapped_column(ForeignKey("catalog_products.id"), index=True)
    source_row_id: Mapped[UUID] = mapped_column(ForeignKey("intake_rows.id"))
    normalizer_version: Mapped[str]
    name: Mapped[str | None]
    supplier_article: Mapped[str | None]
    unit: Mapped[str | None]
    category_code: Mapped[str | None]
    category_year: Mapped[int | None]
    # No canonical overwrite when source names/articles/units disagree.


class Warehouse(Base):
    __tablename__ = "catalog_warehouses"
    id: Mapped[Id]
    name: Mapped[str] = mapped_column(unique=True)
