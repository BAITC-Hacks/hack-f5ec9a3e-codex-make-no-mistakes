"""Public bulk stock-observation ingestion."""

from sqlalchemy import insert

from .models import MonthlyStock, StockObservation


def write_import_batch(connection, batch):
    for name, model in (("monthly_stock", MonthlyStock), ("stock", StockObservation)):
        if batch.get(name):
            connection.execute(insert(model), batch[name])
