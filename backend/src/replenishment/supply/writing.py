"""Public bulk shipment and quantity-rule ingestion."""

from sqlalchemy import insert

from .models import IncomingShipment, IncomingShipmentLine, QuantityRuleObservation


def write_import_batch(connection, batch):
    for name, model in (
        ("shipments", IncomingShipment),
        ("shipment_lines", IncomingShipmentLine),
        ("quantity_rules", QuantityRuleObservation),
    ):
        if batch.get(name):
            connection.execute(insert(model), batch[name])
