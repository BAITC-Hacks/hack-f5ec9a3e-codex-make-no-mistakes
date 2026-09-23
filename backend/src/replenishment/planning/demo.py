"""On-demand synthetic examples. No source or database writes."""

from copy import deepcopy
from datetime import date, timedelta

from replenishment.planning.models import PlanningRequest


def demo_cases() -> list[dict]:
    """Return independent JSON-ready fixtures with explicit synthetic provenance."""
    start = date(2026, 9, 23)
    base = {
        "planning_date": start.isoformat(),
        "lead_time_days": 7,
        "review_days": 2,
        "buffer_days": "2",
        "rows": [
            {
                "row_id": "synthetic-systeme",
                "supplier": "Systeme Electric",
                "sku": "DEMO-SYS-001",
                "name": "Синтетический пример — электрический аппарат",
                "stock_unit": "шт",
                "warehouse": "Алматы",
                "purchase_unit": "шт",
                "free_stock": "50",
                "stock_as_of": start.isoformat(),
                "stock_scope_confirmed": True,
                "incoming_complete": True,
                "constraints_confirmed": True,
                "stock_per_purchase_unit": "1",
                "minimum_order": "0",
                "order_multiple": "1",
                "daily_demand": "20",
                "basis": "synthetic",
                "notes": ["Все значения примера синтетические."],
                "incoming": [
                    {
                        "id": "DEMO-TRANSIT",
                        "quantity": "70",
                        "expected_on": start.isoformat(),
                        "warehouse": "Алматы",
                        "stock_unit": "шт",
                    }
                ],
            }
        ],
    }
    cases = []

    def add(case_id, name, description, payload):
        cases.append(
            {
                "id": case_id,
                "name": name,
                "description": description,
                "input": PlanningRequest.model_validate(payload).model_dump(mode="json"),
            }
        )

    add(
        "baseline",
        "Синтетика: базовый транзит",
        "Спрос 180 + запас 40 − остаток 50 − транзит 70 = заказ 100.",
        base,
    )
    more_transit = deepcopy(base)
    more_transit["rows"][0]["incoming"][0]["quantity"] = "100"
    add(
        "more-transit",
        "Синтетика: больше товара в пути",
        "Транзит вырос с 70 до 100; заказ уменьшился со 100 до 70.",
        more_transit,
    )
    history = deepcopy(base)
    history.update(buffer_days="0", exclude_bulk=True)
    row = history["rows"][0]
    row.update(
        daily_demand=None,
        free_stock="0",
        incoming=[],
        history_start=(start - timedelta(days=84)).isoformat(),
        history_end=(start - timedelta(days=1)).isoformat(),
    )
    row["sales"] = [
        {
            "day": (start - timedelta(days=84 - index)).isoformat(),
            "quantity": "10",
            "document": f"SYNTHETIC-{index}",
            "customer_id": "anonymous-1",
        }
        for index in range(84)
    ]
    bulk = deepcopy(history)
    bulk["rows"][0]["sales"][-8]["quantity"] = "1010"
    add(
        "bulk",
        "Синтетика: разовая крупная закупка",
        "Кандидат 1010 заменяется регулярной частью 10; факт сохранён.",
        bulk,
    )
    seasonal = deepcopy(base)
    seasonal.update(review_days=7, growth_pct="20", seasonality={"9": "1.5", "10": "2"})
    seasonal["rows"][0]["category"] = "DEMO-A"
    add(
        "seasonal-growth",
        "Синтетика: сезонность и рост",
        "Разные множители сентября/октября и рост 20% один раз.",
        seasonal,
    )
    stockout = deepcopy(history)
    stockout["compensate_stockouts"] = True
    stockout_row = stockout["rows"][0]
    stockout_row["stockout_days"] = [sale["day"] for sale in stockout_row["sales"][-7:]]
    stockout_row["sales"] = stockout_row["sales"][:-7]
    add(
        "stockout",
        "Синтетика: известные дни отсутствия",
        "Восстановление спроса по доступным дням той же недели.",
        stockout,
    )
    late = deepcopy(base)
    late.update(review_days=3, buffer_days="0")
    late["rows"][0].update(daily_demand="10", free_stock="20")
    late["rows"][0]["incoming"][0].update(quantity="80", expected_on=(start + timedelta(days=5)).isoformat())
    add(
        "early-shortage",
        "Синтетика: нулевой заказ и ранний дефицит",
        "Итоговая потребность 0, но до прихода возникает дефицит до 30 единиц.",
        late,
    )
    missing = deepcopy(base)
    iek = deepcopy(missing["rows"][0])
    iek.update(
        row_id="synthetic-iek",
        supplier="IEK",
        sku="DEMO-IEK-001",
        name="Синтетический IEK: нужны данные",
        free_stock=None,
        warehouse=None,
        stock_scope_confirmed=False,
        incoming=[],
        stock_per_purchase_unit=None,
        purchase_unit="бухта",
        stock_unit="м",
    )
    missing["rows"].append(iek)
    add(
        "missing-inputs",
        "Синтетика: оба поставщика, неполные данные",
        "Systeme рассчитан; IEK остаётся видимым с неизвестными складом, остатком и конверсией.",
        missing,
    )
    return cases
