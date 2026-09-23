"""Hand-calculated checks against the production monthly evaluator."""

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from decimal import Decimal

import pytest

from evaluation.cases import ROOT, read_batch
from evaluation.test_app import batch
from replenishment.calculation.evaluation import _metric, evaluate, evaluate_origins, promotion_gate


def row(supplier="a", series="one", horizon=1, actual=10, prediction=12, scale=10, unit=None):
    return {
        "supplier": supplier,
        "series_id": series,
        "horizon": horizon,
        "unit": unit,
        "actual": actual,
        "predictions": {"recent_level": prediction},
        "training_scale": Decimal(scale),
    }


def test_normalized_error_balances_observations_horizons_products_and_suppliers():
    # a/one: horizon means 1 and 3 => 2; a/two: 4 => supplier a: 3.
    # Supplier b: 1. Equal supplier weighting => (3 + 1) / 2 = 2.
    rows = [
        row(prediction=20),
        row(prediction=20),
        row(horizon=2, prediction=40),
        row(series="two", prediction=50),
        row(supplier="b", prediction=20),
    ]
    result = _metric(rows, "recent_level")
    assert result["primary_error"] == 2
    assert result["supplier_error"] == {"a": 3, "b": 1}
    assert result["supplier_horizon_error"] == {"a:1": 2.5, "a:2": 3, "b:1": 1}


def test_bias_cancels_within_supplier_but_not_between_suppliers():
    rows = [row(actual=10, prediction=8), row(actual=20, prediction=24)]
    result = _metric(rows, "recent_level")
    assert result["primary_error"] == pytest.approx(0.3)
    assert result["absolute_normalized_bias"] == pytest.approx(0.1)
    assert result["underforecast"] == pytest.approx(0.1)
    assert _metric([row(prediction=8), row(prediction=12)], "recent_level")["absolute_normalized_bias"] == 0
    split = _metric([row(prediction=8), row(supplier="b", prediction=12)], "recent_level")
    assert split["absolute_normalized_bias"] == pytest.approx(0.2)
    for prediction, under in [(8, 0.2), (12, 0)]:
        result = _metric([row(prediction=prediction)], "recent_level")
        assert result["absolute_normalized_bias"] == pytest.approx(0.2)
        assert result["underforecast"] == pytest.approx(under)
    scaled = _metric([row(actual=100, prediction=80, scale=100)], "recent_level")
    assert scaled["underforecast"] == pytest.approx(0.2)


def test_zero_sales_valid_and_zero_scale_explicitly_excluded():
    result = _metric(
        [row(actual=0, prediction=4), row(series="zero", actual=0, prediction=4, scale=0)], "recent_level"
    )
    assert result["evaluated"] == 2 and result["coverage"] == 1
    assert result["normalized_evaluated"] == 1 and result["zero_scale"] == 1
    assert result["zero_scale_series"] == ["a:zero"]
    assert result["primary_error"] == result["absolute_normalized_bias"] == 0.4
    assert result["underforecast"] == 0
    zero = _metric([row(actual=0, prediction=0, scale=0, unit="pcs")], "recent_level")
    assert zero["primary_error"] is zero["absolute_normalized_bias"] is zero["underforecast"] is None
    assert zero["wape"] is None


def test_wape_only_averages_known_supplier_unit_groups():
    rows = [
        row(actual=10, prediction=8, unit="pcs"),
        row(actual=20, prediction=24, unit="pcs"),
        row(actual=100, prediction=150, unit="kg"),
        row(supplier="b", actual=10, prediction=20, unit="pcs"),
        row(actual=100000, prediction=0),
    ]
    result = _metric(rows, "recent_level")
    assert result["wape_by_unit"] == {"a:pcs": 0.2, "a:kg": 0.5, "b:pcs": 1}
    assert result["wape"] == pytest.approx(17 / 30)
    assert _metric([rows[-1]], "recent_level")["wape"] is None


def test_coverage_missing_actuals_and_absent_training_history():
    series = batch()["series"][0]
    result = evaluate_origins([series], ["2025-02-01"])
    assert len(result["rows"]) == 3
    assert result["metrics"]["recent_level"]["coverage"] == 1
    missing = deepcopy(series)
    missing["history"] = [h for h in missing["history"] if h["month"] != "2025-04-01"]
    result = evaluate_origins([missing], ["2025-02-01"])
    assert len(result["rows"]) == 3
    assert result["metrics"]["recent_level"]["evaluated"] == 2
    assert result["metrics"]["recent_level"]["coverage"] == pytest.approx(2 / 3)
    assert result["excluded"] == [
        {
            "series_id": series["series_id"],
            "origin": "2025-02-01",
            "target_month": "2025-04-01",
            "reason": "missing_actual",
        }
    ]
    untrained = {**series, "series_id": "new", "history": series["history"][1:]}
    combined = evaluate_origins([missing, untrained], ["2025-02-01"])
    assert combined["rows"] == result["rows"]  # No-history series never enter the current target ledger.
    assert combined["metrics"] == result["metrics"]
    assert combined["excluded"][-1] == {
        "series_id": "new",
        "origin": "2025-02-01",
        "reason": "no_training_history",
    }
    empty = evaluate_origins([untrained], ["2025-02-01"])
    assert empty["rows"] == [] and empty["metrics"]["recent_level"]["coverage"] == 0


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"primary_error": 97.01}, "development_improvement_below_3_percent"),
        ({"absolute_normalized_bias": 0.21}, "absolute_normalized_bias_worse"),
        ({"coverage": 0.99}, "coverage_reduced"),
        ({"evaluated": 9}, "evaluated_coverage_reduced"),
        ({"supplier_horizon_error": {}}, "supplier_horizon_coverage_reduced:a:1"),
        ({"supplier_horizon_error": {"a:1": 105.01}}, "supplier_horizon_degradation:a:1"),
        ({"primary_error": None}, "missing_or_zero_development_error"),
        ({"absolute_normalized_bias": None}, "missing_bias"),
    ],
)
def test_promotion_boundaries(change, reason):
    champion = {
        "primary_error": 100,
        "absolute_normalized_bias": 0.2,
        "coverage": 1,
        "evaluated": 10,
        "supplier_horizon_error": {"a:1": 100},
    }
    challenger = {**champion, "primary_error": 97, "supplier_horizon_error": {"a:1": 105}}
    assert promotion_gate(champion, challenger) == {"promote": True, "improvement": 0.03, "reasons": []}
    rejected = promotion_gate(champion, {**challenger, **change})
    assert not rejected["promote"] and rejected["reasons"] == [reason]
    assert not promotion_gate({**champion, "primary_error": 0}, challenger)["promote"]


def test_future_actuals_change_scores_without_changing_forecasts_or_frozen_selection():
    series = batch()["series"]
    original = evaluate(series, ["2025-02-01"], ["2025-03-01"])
    changed = deepcopy(series)
    changed[0]["history"].append({"month": "2025-06-01", "quantity": "9999", "evidence": []})
    later = evaluate(changed, ["2025-02-01"], ["2025-03-01"])
    assert later["development"]["rows"] == original["development"]["rows"]
    assert later["development"]["metrics"] == original["development"]["metrics"]
    assert (
        later["selection_frozen"] == original["selection_frozen"] == original["development"]["selected_model"]
    )
    assert later["retrospective"]["metrics"] != original["retrospective"]["metrics"]
    assert [r["predictions"] for r in later["retrospective"]["rows"]] == [
        r["predictions"] for r in original["retrospective"]["rows"]
    ]
    assert later["retrospective_selected"] == later["retrospective"]["metrics"][later["selection_frozen"]]


@pytest.fixture(scope="module")
def real_batch():
    return read_batch()


def test_workbook_loading_deterministic_and_source_hashes_unchanged(real_batch):
    assert read_batch() == real_batch
    assert {s["supplier"] for s in real_batch["series"]} == {"iek", "systeme"}
    assert len({s["series_id"] for s in real_batch["series"]}) == len(real_batch["series"])
    assert all(s["unit"] is None for s in real_batch["series"])
    assert all(h["month"] < "2026-09-01" for s in real_batch["series"] for h in s["history"])
    for source in real_batch["source_selection"]:
        assert hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest() == source["sha256"]


def test_source_corruption_fails(tmp_path):
    manifest = json.loads((ROOT / "docs/sources/manifest.json").read_text(encoding="utf-8"))
    target = tmp_path / "docs/sources/manifest.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(manifest))
    for source in manifest:
        if "Ежемесячные продажи" in source.get("path", ""):
            path = tmp_path / source["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash/size mismatch"):
        read_batch(root=tmp_path)


def test_current_cli_printed_metrics_agree_with_json(tmp_path):
    source, output = tmp_path / "batch.json", tmp_path / "report.json"
    source.write_text(json.dumps(batch()))
    command = [
        sys.executable,
        str(ROOT / "scripts/evaluate.py"),
        "--batch",
        str(source),
        "--output",
        str(output),
        "--development-origin",
        "2025-02-01",
        "--retrospective-origin",
        "2025-03-01",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    printed = json.loads(completed.stdout)
    report = json.loads(output.read_text())
    selected = report["selection_frozen"]
    assert selected is not None
    assert printed == {
        "protocol": report["protocol"],
        "series": report["series_count"],
        "leftovers_comparison": {
            key: report["leftovers_comparison"][key]
            for key in ("status", "message", "eligible_count", "excluded_count", "missing_input_counts")
        },
        "selected_model": selected,
        "development_primary_error": report["development"]["metrics"][selected]["primary_error"],
        "retrospective_primary_error": report["retrospective_selected"]["primary_error"],
        "development_runtime_seconds": report["development"]["runtime_seconds"],
    }
    assert printed["leftovers_comparison"]["message"] == "Leftover reduction: not measured."
    assert report["leftovers_comparison"]["eligible_cases"] == []
    assert all(
        case["leftover_reduction_percent"] is None
        for case in report["leftovers_comparison"]["excluded_cases"]
    )
    assert report["protocol"] == "monthly-forecast-evaluation-v2"
    assert report["selection_frozen_before_retrospective"] is True
    before = output.read_bytes()
    repeated = subprocess.run(command, capture_output=True, text=True)
    assert repeated.returncode != 0 and "FileExistsError" in repeated.stderr
    assert output.read_bytes() == before


def test_retrospective_winner_cannot_replace_development_selection():
    series = batch()["series"]
    series[0]["history"] = [
        {"month": f"2025-{month:02}-01", "quantity": str(quantity), "evidence": []}
        for month, quantity in enumerate([30, 100, 10, 0, 2, 30, 10, 10, 2, 2, 10, 0], 1)
    ]
    result = evaluate(series, ["2025-04-01"], ["2025-09-01"])
    assert result["development"]["selected_model"] == "recent_level"
    assert result["retrospective"]["selected_model"] == "ewma_adjusted"
    assert result["selection_frozen"] == "recent_level"
    assert result["retrospective_selected"] == result["retrospective"]["metrics"]["recent_level"]


def test_coverage_requires_both_actual_and_model_prediction():
    result = _metric([row(), row(actual=None), row(prediction=None)], "recent_level")
    assert result["evaluated"] == result["normalized_evaluated"] == 1
    assert result["coverage"] == pytest.approx(1 / 3)
