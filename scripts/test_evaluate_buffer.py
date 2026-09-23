from datetime import date

from evaluate_buffer import calibrate, pinball, replay, targets


def test_mature_labels_and_segment_fallback():
    rows = [
        {"origin": date(2025, month, 1), "segment": "regular", "residual": month} for month in range(7, 13)
    ]
    assert calibrate(rows, date(2025, 12, 21), "regular")["q"] is None
    fit = calibrate(rows, date(2025, 12, 22), "intermittent")
    assert fit["q"] == 12 and fit["scope"] == "supplier_unit" and fit["origin_count"] == 6
    rows.append({"origin": date(2026, 1, 1), "segment": "regular", "residual": 999999})
    assert calibrate(rows, date(2026, 1, 1), "regular")["q"] == 12
    assert targets(21, {"q": None}) == (28, 28)
    assert targets(21, {"q": -5}) == (28, 21)
    assert pinball(10, 8) > pinball(10, 12)


def test_inventory_timing_backlog_and_terminal_pipeline():
    demand = [1.0] * 21
    on_time = replay(demand, {0: 21}, 0, 0, False, warmup=0)
    delayed = replay(demand, {0: 21}, 0, 7, False, warmup=0)
    backlog = replay(demand, {0: 21}, 0, 0, True, warmup=0)
    assert on_time["immediately_served"] == 7 and on_time["terminal_stock"] == 14
    assert delayed["immediately_served"] == 0 and delayed["terminal_pipeline"] == 21
    assert backlog["immediately_served"] == 7 and backlog["terminal_stock"] == 0
    assert backlog["terminal_backlog"] == 0 and backlog["backlog_unit_days"] == sum(range(1, 15))
