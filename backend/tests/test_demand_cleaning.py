from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from replenishment.demand.cleaning import Order, clean_orders, movement_reason


def orders(values):
    return [Order("supplier", "001_", "шт", "Алматы", date(2025, 1, 1) + timedelta(days=i),
                  str(i), Decimal(str(value)), (i + 2,)) for i, value in enumerate(values)]


def test_bulk_growth_and_as_of_evidence():
    steady = orders([10] * 80)
    spike = steady.copy()
    spike[-4] = replace(spike[-4], quantity=Decimal(1010))
    cutoff = date(2025, 3, 22)
    clean = clean_orders(spike, as_of=cutoff)
    assert sum(d.regular_quantity for d in clean) == Decimal(800)
    flagged = [d for d in clean if d.excluded_quantity]
    assert len(flagged) == 1 and flagged[0].excluded_quantity == 1000
    assert flagged[0].order.source_rows == (78,)
    for growth in ([10] * 60 + [20] * 20, [10] * 60 + [100] * 20):
        result = clean_orders(orders(growth), as_of=cutoff)
        assert [d.regular_quantity for d in result] == growth
    # Future persistent growth must not retrospectively unflag a past origin.
    extended = orders([10] * 76 + [1010] * 10)
    origin = extended[77].day
    assert clean_orders(extended, as_of=origin) == clean_orders(extended[:77], as_of=origin)
    assert clean_orders(extended, as_of=origin)[-1].excluded_quantity == 1000
    assert all(d.excluded_quantity == 0 for d in clean_orders(extended, as_of=cutoff))


def test_sparse_units_warehouses_and_duplicate_documents():
    sparse = orders([1, 1000])
    assert all(d.reason == "insufficient_history" for d in clean_orders(sparse, as_of=date(2026, 1, 1)))
    sample = orders([10] * 20 + [1000])
    sample[-1] = replace(sample[-1], unit="м")
    assert clean_orders(sample, as_of=date(2026, 1, 1))[-1].regular_quantity == 1000
    sample[-1] = replace(sample[-1], unit="шт", warehouse="Other")
    assert clean_orders(sample, as_of=date(2026, 1, 1))[-1].regular_quantity == 1000
    with pytest.raises(ValueError, match="duplicate order"):
        clean_orders(sparse + sparse, as_of=date(2026, 1, 1))
    with pytest.raises(ValueError, match="finite positive"):
        clean_orders([replace(sparse[0], quantity=Decimal("NaN"))], as_of=date(2026, 1, 1))


def test_movement_classification_preserves_unknowns():
    outgoing = "Расходная накладная 123"
    for quantity, reason in ((None, "missing_quantity"), (Decimal("NaN"), "invalid_quantity"),
                             (Decimal(-3), "negative_unresolved"), (Decimal(0), "zero_quantity"),
                             (Decimal(3), "positive_outgoing")):
        assert movement_reason(outgoing, quantity) == reason
    assert movement_reason("Заказ покупателя", Decimal(3)) == "other_document"


def test_same_day_orders_are_not_sustained_growth_or_threshold_history():
    sample = orders([10] * 20 + [1000] * 3)
    sample[-2:] = [replace(o, day=sample[-3].day) for o in sample[-2:]]
    result = clean_orders(sample, as_of=date(2025, 2, 1))
    assert [d.regular_quantity for d in result[-3:]] == [10, 10, 10]
    assert [d.history_orders for d in result[-3:]] == [20, 20, 20]
    assert all(d.threshold == 40 for d in result[-3:])
