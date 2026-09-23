"""Immutable evaluation artifact validation and compatibility with the existing registry."""

import copy
import csv
import hashlib
import importlib.util
import json
from collections import defaultdict
from pathlib import Path

import pytest

from replenishment.evaluation import artifacts
from replenishment.metrics import forecast_metrics


def summaries(predictions):
    groups = defaultdict(list)
    for row in predictions:
        groups[tuple(row[field] for field in artifacts.GROUP_FIELDS) + (row["model_id"],)].append(row)
    metrics = []
    for key, rows in groups.items():
        metrics.append({
            **dict(zip(artifacts.GROUP_FIELDS + ("model",), key, strict=True)), "segment": "all",
            **forecast_metrics([row["actual"] for row in rows], [row["forecast"] for row in rows],
                               mae_scales=[row["mae_scale"] for row in rows],
                               mse_scales=[row["mse_scale"] for row in rows]),
            "sku_count": len({row["sku"] for row in rows}),
            "origin_count": len({row["origin"] for row in rows}),
        })
    return metrics


@pytest.fixture
def sample(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "ROOT", tmp_path)
    source = tmp_path / "data.xlsx"
    source.write_bytes(b"synthetic source evidence")
    scripts = [tmp_path / "backend" / "runner.py", tmp_path / "scripts" / "runner.py"]
    for index, script in enumerate(scripts):
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(f"print({index})\n", encoding="utf-8")
    predictions = [{
        "supplier": "Systeme", "warehouse": "Алматы", "unit": "piece", "sku": sku,
        "origin": origin, "horizon": 7, "phase": phase, "segment": "regular", "model_id": model,
        "actual": actual, "forecast": actual + offset, "mae_scale": 2.0, "mse_scale": 4.0,
    } for origin, phase in (("2025-07-01", "development_2025"), ("2026-01-01", "retrospective_2026"))
      for model, offset in (("backend_raw", 2.0), ("mean28", 1.0))
      for sku, actual in (("001", 5.0), ("002", 0.0))]
    summary = {
        "models": ["backend_raw", "mean28"], "metrics": summaries(predictions),
        "monthly_metrics": [{"note": "preserve exact supplied monthly metadata"}],
        "source_files": [{"supplier": "Systeme", "source": "data.xlsx",
                          "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}],
        "configuration": {"baseline": "mean28", "limit_per_group": 2},
        "gates": [{"status": "fail", "reasons": ["Insufficient WAPE improvement"]}],
        "operational_metrics": {"fill_rate": {"status": "not_evaluated", "reason": "No availability"}},
        "environment": {"python": "fixture"}, "elapsed_seconds": 1.25,
        "unrecognized_extra_metadata": {"preserve": True},
    }
    return tmp_path / "new-run", predictions, summary, scripts


def write(sample):
    output, predictions, summary, scripts = sample
    return artifacts.write_run(output, predictions, summary, code_files=scripts,
                               reproduction_command="uv run python -m replenishment.cli.evaluate")


def test_write_preserves_metadata_nested_snapshots_and_registry_target_hash(sample):
    output, predictions, summary, scripts = sample
    original = copy.deepcopy((predictions, summary))
    manifest = write(sample)
    assert (predictions, summary) == original
    assert json.loads((output / "results.json").read_text(encoding="utf-8")) == summary
    assert manifest["configuration"] == summary["configuration"]
    assert manifest["gates"] == summary["gates"]
    assert manifest["operational_metrics"] == summary["operational_metrics"]
    assert manifest["environment"] == summary["environment"]
    assert manifest["legacy_registry_compatible"] is True
    assert manifest["verified_full_cohort_metric_groups"] == 4
    for script in scripts:
        relative = script.relative_to(output.parent).as_posix()
        assert (output / "code" / relative).read_bytes() == script.read_bytes()
        assert manifest["code_sha256"][relative] == hashlib.sha256(script.read_bytes()).hexdigest()
    for path, info in manifest["files"].items():
        assert info["sha256"] == hashlib.sha256((output / path).read_bytes()).hexdigest()
    with (output / "predictions.csv").open(encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == len(predictions)
    registry_path = Path(__file__).resolve().parents[2] / "scripts" / "register_experiment.py"
    spec = importlib.util.spec_from_file_location("evaluation_registry_test", registry_path)
    registry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(registry)
    target_hash, target_count, checked = registry.inspect_predictions(
        output, summary["models"], copy.deepcopy(summary["metrics"])
    )
    assert manifest["target_sha256"] == target_hash
    assert manifest["target_rows"] == target_count == 4
    assert manifest["verified_full_cohort_metric_groups"] == checked
    report = (output / "report.md").read_text(encoding="utf-8")
    assert "retrospective" in report and "MASE" in report and "RMSSE" in report
    assert "limited smoke cohort" in report and "not_evaluated" in report


@pytest.mark.parametrize("mutation,match", [
    ("missing", "cohort"), ("duplicate", "Duplicate"), ("nonfinite", "finite"),
    ("negative", "nonnegative"), ("different_actual", "Different actual"),
    ("different_scale", "scales"), ("warehouse_collision", "warehouses collide"),
    ("different_warehouse", "warehouses collide"), ("phase", "phase"),
])
def test_rejects_invalid_or_nonidentical_prediction_cohorts(sample, mutation, match):
    output, predictions, _, _ = sample
    if mutation == "missing":
        predictions.pop()
    elif mutation == "duplicate":
        predictions.append(dict(predictions[0]))
    elif mutation == "nonfinite":
        predictions[0]["forecast"] = float("inf")
    elif mutation == "negative":
        predictions[0]["forecast"] = -1.0
    elif mutation == "different_actual":
        predictions[2]["actual"] = 10.0
    elif mutation == "different_scale":
        predictions[2]["mae_scale"] = None
    elif mutation == "warehouse_collision":
        predictions.extend({**row, "warehouse": "Astana"} for row in predictions.copy())
    elif mutation == "different_warehouse":
        predictions[2]["warehouse"] = "Astana"
    else:
        predictions[0]["phase"] = "retrospective_2026"
    with pytest.raises(ValueError, match=match):
        write(sample)
    assert not output.exists()


@pytest.mark.parametrize("field", ["n", "actual_qty", "predicted_qty", "wape_pct", "bias_pct", "mae", "rmse",
                                   "mase", "rmsse", "mase_n", "rmsse_n", "sku_count", "origin_count"])
def test_recalculates_all_metric_fields_and_rejects_tampering(sample, field):
    output, _, summary, _ = sample
    summary["metrics"][0][field] += 1
    with pytest.raises(ValueError, match="Metric mismatch"):
        write(sample)
    assert not output.exists()


@pytest.mark.parametrize("change", ["missing", "duplicate", "warehouse"])
def test_rejects_missing_or_duplicate_all_cohort_metric_groups(sample, change):
    output, _, summary, _ = sample
    if change == "missing":
        summary["metrics"].pop()
    elif change == "duplicate":
        summary["metrics"].append(dict(summary["metrics"][0]))
    else:
        summary["metrics"][0]["warehouse"] = "Unmatched"
    with pytest.raises(ValueError):
        write(sample)
    assert not output.exists()


def test_refuses_overwrite_and_changed_source_or_code(sample):
    output, _, summary, scripts = sample
    summary["code_sha256"] = {scripts[0].relative_to(output.parent).as_posix(): "0" * 64}
    with pytest.raises(ValueError, match="Code hash changed"):
        write(sample)
    assert not output.exists()
    summary.pop("code_sha256")
    summary["source_files"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Source hash changed"):
        write(sample)
    assert not output.exists()
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("existing run", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write(sample)
    assert marker.read_text(encoding="utf-8") == "existing run"


def test_nonfinite_metadata_and_failed_manifest_write_leave_no_success(sample, monkeypatch):
    output, _, summary, _ = sample
    summary["elapsed_seconds"] = float("nan")
    with pytest.raises(ValueError):
        write(sample)
    assert not output.exists()
    summary["elapsed_seconds"] = 1.25
    original = Path.write_bytes

    def fail_manifest(path, content):
        if path.name == ".manifest.json.tmp":
            raise OSError("Simulated full disk")
        return original(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail_manifest)
    with pytest.raises(OSError, match="full disk"):
        write(sample)
    assert not output.exists()


def test_disjoint_warehouse_targets_are_labelled_incompatible_with_legacy_grouping(sample):
    output, predictions, summary, _ = sample
    for row in predictions:
        if row["sku"] == "002":
            row["warehouse"] = "Astana"
    summary["metrics"] = summaries(predictions)
    manifest = write(sample)
    assert manifest["legacy_registry_compatible"] is False
    assert "Legacy registry is incompatible" in (output / "report.md").read_text(encoding="utf-8")
