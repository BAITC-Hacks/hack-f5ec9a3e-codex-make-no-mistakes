from datetime import date, timedelta
from fractions import Fraction

import pytest
from pydantic import ValidationError

from replenishment.planning.calculator import calculate
from replenishment.planning.demo import demo_cases
from replenishment.planning.models import PlanningRequest


def test_custom_period_is_inclusive_and_preserves_arrival_date():
    payload = demo_cases()[0]["input"]
    payload.update(forecast_end="2026-09-25", forecast_method="auto", buffer_days="0")
    payload["rows"][0].update(daily_demand="10", incoming=[])
    request = PlanningRequest.model_validate(payload)
    row = calculate(request).rows[0]
    assert row.coverage_end == date(2026, 9, 26)
    assert row.forecast_demand == 30
    assert len(row.daily_balances) == 3
    assert row.arrival_date > date(2026, 9, 25)
    assert row.forecast_method == "manual_daily_demand"
    for end in ("2026-09-22", "2028-09-23"):
        with pytest.raises(ValidationError):
            PlanningRequest.model_validate({**payload, "forecast_end": end})


def test_auto_weights_recent_weeks_without_capping_and_falls_back_for_short_history():
    payload = demo_cases()[0]["input"]
    payload.update(forecast_end="2026-10-09", forecast_method="auto", compensate_stockouts=False)
    end = date(2026, 9, 22)
    payload["rows"][0].update(
        daily_demand=None, history_start=end - timedelta(days=55), history_end=end,
        sales=[{"day": end, "quantity": "1000", "document": "bulk"}], stockout_days=[],
    )
    row = calculate(PlanningRequest.model_validate(payload)).rows[0]
    expected = Fraction(1000) / sum(Fraction(72, 100) ** (age // 7) for age in range(56))
    assert row.forecast_method == "weekly_ewma"
    assert float(row.daily_demand) == pytest.approx(float(expected))
    assert row.excluded_bulk_quantity == 0
    payload["rows"][0]["history_start"] = end - timedelta(days=9)
    row = calculate(PlanningRequest.model_validate(payload)).rows[0]
    assert row.forecast_method == "history_mean"
    assert row.daily_demand == 100
