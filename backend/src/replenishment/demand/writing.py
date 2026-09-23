"""Public bulk source-observation ingestion; no demand interpretation."""

from sqlalchemy import insert

from .models import MonthlySales, ReportMetric, SalesMovement, SeasonalityObservation


def write_import_batch(connection, batch):
    for name, model in (
        ("movements", SalesMovement),
        ("monthly_sales", MonthlySales),
        ("report_metrics", ReportMetric),
        ("seasonality", SeasonalityObservation),
    ):
        if batch.get(name):
            connection.execute(insert(model), batch[name])
