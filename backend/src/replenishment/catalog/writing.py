"""Public import commands; the caller owns the workbook transaction."""

from uuid import uuid4

from sqlalchemy import insert, select

from .models import Product, ProductObservation, Supplier, Warehouse


def identities(connection, code):
    supplier = connection.execute(select(Supplier.id).where(Supplier.code == code)).scalar_one_or_none()
    if supplier is None:
        supplier = uuid4()
        connection.execute(
            insert(Supplier),
            {"id": supplier, "code": code, "name": "IEK" if code == "iek" else "Systeme Electric"},
        )
    products = dict(
        connection.execute(select(Product.sku, Product.id).where(Product.supplier_id == supplier)).all()
    )
    warehouses = dict(connection.execute(select(Warehouse.name, Warehouse.id)).all())
    return supplier, products, warehouses


def write_import_batch(connection, products, warehouses, observations):
    for model, rows in ((Product, products), (Warehouse, warehouses), (ProductObservation, observations)):
        if rows:
            connection.execute(insert(model), rows)
