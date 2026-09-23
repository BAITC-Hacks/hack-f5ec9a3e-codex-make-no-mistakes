"""Compact evidence-gate checks; synthetic fixtures are not historical evidence."""

from copy import deepcopy

from evaluation.cases import read_batch
from evaluation.leftovers import coverage_case, leftovers_comparison


def series(supplier="iek", sku="exact", unit="pcs"):
    return {
        "supplier": supplier,
        "sku": sku,
        "unit": unit,
        "series_id": sku,
        "history": [
            {"month": month, "quantity": "0", "evidence": []}
            for month in ["2025-12-01", *[f"2026-{m:02}-01" for m in range(1, 10)]]
        ],
    }


def test_boundary_alignment_and_missing_not_zero():
    sales = series()
    opening = coverage_case(sales, [sales], "2026-01-01", "2026-04-01", "opening")
    closing = coverage_case(sales, [sales], "2026-01-01", "2026-04-01", "closing")
    assert opening["starting_stock"]["month"] == "2026-01-01"
    assert opening["ending_stock"]["month"] == "2026-05-01"
    assert closing["starting_stock"]["month"] == "2025-12-01"
    assert closing["ending_stock"]["month"] == "2026-04-01"
    second = coverage_case(sales, [sales], "2026-05-01", "2026-08-01", "opening")
    assert second["starting_stock"]["month"] == "2026-05-01"
    assert second["ending_stock"]["month"] == "2026-09-01"
    assert opening["ending_stock"]["quantity"] == 0
    assert not any(m.startswith("ending_stock:") for m in opening["missing_inputs"])
    missing = deepcopy(sales)
    missing["history"][5]["quantity"] = None
    result = coverage_case(sales, [missing], "2026-01-01", "2026-04-01", "opening")
    assert "ending_stock:2026-05-01" in result["missing_inputs"]
    assert result["ending_stock"]["quantity"] is None


def test_identity_units_and_ambiguous_scenarios_never_qualify():
    sales = series("systeme")
    batch = {"series": [sales], "source_selection": []}
    for stock in [series("iek"), series("systeme", "EXACT"), series("systeme", unit="kg"), sales]:
        result = leftovers_comparison(batch, {"series": [stock], "source_selection": []})
        assert result["eligible_cases"] == [] and result["eligible_count"] == 0
        assert result["message"] == "Leftover reduction: not measured."
        assert len(result["exploratory_data_coverage"]) == 4
        for case in result["excluded_cases"] + result["exploratory_data_coverage"]:
            assert case["leftover_reduction_percent"] is None
            assert case["unmet_recorded_sales"] is None
            assert "historical_open_orders_and_deliveries_including_verified_zero" in case["missing_inputs"]
        if stock["supplier"] != sales["supplier"] or stock["sku"] != sales["sku"]:
            assert (
                "unique_stock_match_by_supplier_and_exact_sku"
                in result["excluded_cases"][0]["missing_inputs"]
            )
        if stock["unit"] != sales["unit"]:
            assert "compatible_verified_units" in result["excluded_cases"][0]["missing_inputs"]


def test_pinned_stock_coverage_is_blocked_and_cited():
    sales, stock = read_batch(), read_batch(kind="monthly_stock")
    result = leftovers_comparison(sales, stock)
    assert len(result["source_selection"]) == 4
    assert result["excluded_count"] == 2 * len(sales["series"])
    assert result["eligible_count"] == 0
    assert {c["interpretation"] for c in result["exploratory_data_coverage"]} == {"opening", "closing"}
    assert any(c["ending_stock"]["evidence"] for c in result["excluded_cases"] if c["supplier"] == "iek")
    assert all(c["leftover_reduction_percent"] is None for c in result["excluded_cases"])
