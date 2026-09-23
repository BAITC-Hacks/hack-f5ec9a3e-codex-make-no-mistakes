"""Explainable research policy for gross outgoing demand; no source or database writes.

Negative movements are unresolved corrections, NOT confirmed returns. Bulk flags
are statistical candidates, not evidence of customer concentration.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

POLICY_VERSION = "document-mad-v1"
LOOKBACK_DAYS = 56
MIN_ORDERS = 8
MIN_ACTIVE_DAYS = 4
PERSISTENCE_DAYS = 7
PERSISTENCE_COUNT = 3


def movement_reason(document: str, quantity: Decimal | None) -> str:
    if quantity is None:
        return "missing_quantity"
    if not quantity.is_finite():
        return "invalid_quantity"
    if quantity < 0:
        return "negative_unresolved"
    if quantity == 0:
        return "zero_quantity"
    if not document.startswith("Расходная накладная"):
        return "other_document"
    return "positive_outgoing"


@dataclass(frozen=True)
class Order:
    supplier: str
    sku: str
    unit: str
    warehouse: str
    day: date
    document: str
    quantity: Decimal
    source_rows: tuple[int, ...]


@dataclass(frozen=True)
class CleaningDecision:
    order: Order
    regular_quantity: Decimal
    reason: str
    history_orders: int
    median_quantity: Decimal | None = None
    threshold: Decimal | None = None

    @property
    def excluded_quantity(self) -> Decimal:
        return self.order.quantity - self.regular_quantity


def clean_orders(orders: list[Order], *, as_of: date) -> list[CleaningDecision]:
    """Clean only orders strictly before as_of, independently per SKU/unit/warehouse.

Compare document totals with positive orders in the preceding 56 calendar days
(same-day peers excluded). Flag above max(4*median, median+6*MAD), replacing the
candidate with the median. Retain elevated orders recurring on >=3 distinct days
within +/-7 days, using ONLY evidence before as_of. Very recent flags can thus be
revised when growth is established; callers must recompute at each forecast origin.
Sparse/new series are retained without a threshold. Raw values remain in decisions.
"""
    groups = defaultdict(list)
    identities = set()
    for order in orders:
        if order.day >= as_of:
            continue
        if not order.quantity.is_finite() or order.quantity <= 0:
            raise ValueError("Orders must have finite positive Decimal quantities")
        key = (order.supplier, order.sku, order.unit, order.warehouse)
        identity = (*key, order.day, order.document)
        if identity in identities:
            raise ValueError("Aggregate document lines before cleaning; duplicate order identity")
        identities.add(identity)
        groups[key].append(order)
    decisions = []
    for group in groups.values():
        group.sort(key=lambda order: (order.day, order.document))
        left = day_start = 0
        for i, order in enumerate(group):
            if i == 0 or order.day != group[i - 1].day:
                day_start = i
            while group[left].day < order.day - timedelta(days=LOOKBACK_DAYS):
                left += 1
            past = group[left:day_start]
            reason, regular, center, threshold = "insufficient_history", order.quantity, None, None
            if len(past) >= MIN_ORDERS and len({p.day for p in past}) >= MIN_ACTIVE_DAYS:
                center = median([p.quantity for p in past])
                mad = median([abs(p.quantity - center) for p in past])
                threshold = max(4 * center, center + 6 * mad)
                reason = "regular"
                if order.quantity > threshold:
                    # Only the local neighborhood is inspected; no future-as-of evidence.
                    high_days = {order.day}
                    for direction in (-1, 1):
                        j = i + direction
                        while 0 <= j < len(group) and abs((group[j].day - order.day).days) <= PERSISTENCE_DAYS:
                            if group[j].quantity > threshold:
                                high_days.add(group[j].day)
                            j += direction
                    if len(high_days) >= PERSISTENCE_COUNT:
                        reason = "sustained_elevation_retained"
                    else:
                        reason, regular = "bulk_candidate_median_replacement", center
            decisions.append(CleaningDecision(order, regular, reason, len(past), center, threshold))
    return decisions
