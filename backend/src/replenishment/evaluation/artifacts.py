"""Validate and freeze a completed evaluation using the existing file-based registry format."""

import csv
import hashlib
import io
import json
import math
import shutil
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from replenishment.metrics import forecast_metrics

ROOT = Path(__file__).resolve().parents[4]
PREDICTION_FIELDS = (
    "supplier", "warehouse", "unit", "sku", "origin", "horizon", "phase", "segment", "model_id",
    "actual", "forecast", "mae_scale", "mse_scale",
)
GROUP_FIELDS = ("phase", "supplier", "warehouse", "unit", "horizon")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _number(value, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite nonnegative number")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f"{label} must be a finite nonnegative number") from error
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be a finite nonnegative number")
    return number


def _validated_predictions(predictions: list[dict], models: list[str]):
    if not predictions or not models or len(set(models)) != len(models):
        raise ValueError("Predictions and a unique nonempty model list are required")
    if any(not isinstance(model, str) or not model.strip() for model in models):
        raise ValueError("Model identifiers must be nonblank strings")
    cohorts = {model: set() for model in models}
    targets, legacy_targets, legacy_warehouses, target_context = {}, {}, {}, {}
    groups = defaultdict(list)
    normalized = []
    for original in predictions:
        if missing := set(PREDICTION_FIELDS) - original.keys():
            raise ValueError(f"Prediction is missing fields: {sorted(missing)}")
        row = {field: original[field] for field in PREDICTION_FIELDS}
        for field in ("supplier", "warehouse", "unit", "sku", "model_id"):
            if not isinstance(row[field], str) or not row[field].strip():
                raise ValueError(f"Prediction {field} must be a nonblank string")
        origin = date.fromisoformat(row["origin"])
        if row["origin"] != origin.isoformat() or origin.year not in (2025, 2026):
            raise ValueError("Registry protocol requires ISO origins in 2025 or 2026")
        expected_phase = "development_2025" if origin.year == 2025 else "retrospective_2026"
        if row["phase"] != expected_phase or row["segment"] not in ("regular", "intermittent"):
            raise ValueError("Prediction phase or segment does not match the evaluation protocol")
        if isinstance(row["horizon"], bool) or not isinstance(row["horizon"], int) or row["horizon"] < 1:
            raise ValueError("Prediction horizon must be a positive integer")
        for field in ("actual", "forecast", "mae_scale", "mse_scale"):
            if row[field] is None and field.endswith("_scale"):
                continue
            row[field] = _number(row[field], field)
        model = row["model_id"]
        if model not in cohorts:
            raise ValueError(f"Unexpected prediction model: {model}")
        key = tuple(row[field] for field in ("supplier", "warehouse", "sku", "unit", "origin", "horizon"))
        if key in cohorts[model]:
            raise ValueError(f"Duplicate prediction target for {model}: {key}")
        cohorts[model].add(key)
        if key in targets and targets[key] != row["actual"]:
            raise ValueError(f"Different actual quantities for the same target: {key}")
        context = (row["phase"], row["segment"], row["mae_scale"], row["mse_scale"])
        if key in target_context and target_context[key] != context:
            raise ValueError(f"Different target segment or training scales across models: {key}")
        targets[key], target_context[key] = row["actual"], context
        legacy_key = tuple(row[field] for field in ("supplier", "sku", "unit", "origin", "horizon"))
        if legacy_key in legacy_warehouses and legacy_warehouses[legacy_key] != row["warehouse"]:
            raise ValueError("Multiple warehouses collide under the legacy registry target key; "
                             "evaluate warehouses separately before registration")
        legacy_targets[legacy_key], legacy_warehouses[legacy_key] = row["actual"], row["warehouse"]
        groups[tuple(row[field] for field in GROUP_FIELDS) + (model,)].append(row)
        normalized.append(row)
    target_keys = set(targets)
    for model, cohort in cohorts.items():
        if cohort != target_keys:
            raise ValueError(f"Incomplete or different target cohort for {model}")
    canonical = json.dumps(sorted((list(key), value) for key, value in legacy_targets.items()),
                           ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return normalized, groups, _digest(canonical.encode("utf-8")), len(targets)


def _verify_metrics(groups: dict, metrics: list[dict]) -> int:
    verified = set()
    for metric in metrics:
        if metric["segment"] != "all":
            continue
        key = tuple(metric[field] for field in GROUP_FIELDS) + (metric["model"],)
        if key in verified or key not in groups:
            raise ValueError(f"Duplicate or unexpected all-cohort metric group: {key}")
        rows = groups[key]
        calculated = forecast_metrics(
            [row["actual"] for row in rows], [row["forecast"] for row in rows],
            mae_scales=[row["mae_scale"] for row in rows], mse_scales=[row["mse_scale"] for row in rows],
        )
        calculated.update(sku_count=len({row["sku"] for row in rows}),
                          origin_count=len({row["origin"] for row in rows}))
        for field, expected in calculated.items():
            if field not in metric:
                raise ValueError(f"Missing metric {field}: {key}")
            actual = metric[field]
            if expected is None:
                equal = actual is None
            elif isinstance(expected, int):
                equal = isinstance(actual, int) and not isinstance(actual, bool) and actual == expected
            else:
                equal = (isinstance(actual, (int, float)) and not isinstance(actual, bool)
                         and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-9,
                                                                  abs_tol=1e-9))
            if not equal:
                raise ValueError(f"Metric mismatch for {field}: {key}; expected {expected}, got {actual}")
        verified.add(key)
    if verified != set(groups):
        raise ValueError("Some prediction groups have no all-cohort metrics")
    return len(verified)


def _csv(rows: list[dict], fields) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _report(summary: dict, command: str, compatible: bool) -> str:
    lines = ["# Backend forecast evaluation", "",
             "2026 is a known retrospective period. These scores measure gross-positive recorded sales, "
             "not latent regular demand or inventory performance.", "",
             "## Retrospective all-cohort metrics", "",
             "| Supplier | Warehouse | Unit | Horizon | Model | n | WAPE % | Bias % | MASE | RMSSE |",
             "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |"]
    for metric in summary["metrics"]:
        if metric["phase"] != "retrospective_2026" or metric["segment"] != "all":
            continue
        identity = [_cell(metric[key]) for key in ("supplier", "warehouse", "unit", "horizon", "model", "n")]
        scores = ["undefined" if metric[key] is None else f"{metric[key]:.4f}"
                  for key in ("wape_pct", "bias_pct", "mase", "rmsse")]
        lines.append("| " + " | ".join(identity + scores) + " |")
    lines += ["", "## Promotion gates", "", "Configured internal gates are not industry standards.", "",
              "```json", _json(summary["gates"]).rstrip(), "```", "", "## Caveats", "",
              "- Missing sales days are zero recorded positive sales, not confirmed zero demand.",
              "- Units and warehouses remain separate. Segments and scales use historical data only.",
              "- Forecast errors do not establish fill rate, stockout duration, or inventory savings.",
              "- Operational evaluation needs exact availability, stock/receipt timing, agreed lead/review "
              "policies, and demand treatment; synthetic acceptance tests are separate mechanism checks.",
              "- Target and metric consistency are verified here; this is not an independent leakage audit."]
    if not compatible:
        lines.append("- Legacy registry is incompatible: multiple warehouse metric groups collapse under "
                     "its warehouse-free grouping. Register separate warehouse evaluations.")
    if summary.get("configuration", {}).get("limit_per_group") is not None:
        lines.append("- This run uses a limited smoke cohort; it is not the full-data evaluation.")
    lines += ["", "Recorded operational metrics:", "", "```json",
              _json(summary["operational_metrics"]).rstrip(), "```", "", "## Reproduce", "",
              "Restore code snapshots to their original repository-relative paths before running:", "",
              "```text", command, "```", ""]
    return "\n".join(lines)


def write_run(
    output_dir: Path, predictions: list[dict], summary: dict, *, code_files: list[Path],
    reproduction_command: str,
) -> dict:
    """Validate first, reserve a new directory, and publish the success manifest last.

    Legacy target hashes intentionally omit warehouse to match register_experiment.py.
    Colliding warehouse targets are rejected; other incompatible warehouse groupings
    are labelled in the manifest and report instead of claiming registry compatibility.
    """
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError(f"Evaluation output already exists: {output_dir}")
    required = {"source_files", "models", "metrics", "monthly_metrics", "configuration", "gates",
                "operational_metrics", "environment", "elapsed_seconds"}
    if missing := required - summary.keys():
        raise ValueError(f"Evaluation summary is missing fields: {sorted(missing)}")
    summary_json = _json(summary)  # Reject nonfinite metadata before creating any output.
    rows, groups, target_hash, target_count = _validated_predictions(predictions, summary["models"])
    checked = _verify_metrics(groups, summary["metrics"])
    legacy_groups = {(key[0], key[1], key[3], key[4], key[5]) for key in groups}
    compatible = len(legacy_groups) == len(groups)
    sources = []
    for source in summary["source_files"]:
        path = (ROOT / source["source"]).resolve()
        actual_hash = _digest(path.read_bytes())
        if actual_hash != source["sha256"]:
            raise ValueError(f"Source hash changed since evaluation: {source['source']}")
        sources.append((source["supplier"], actual_hash))
    if not sources or not code_files or not reproduction_command.strip():
        raise ValueError("Source files, code snapshots and a reproduction command are required")
    snapshots = {}
    code_hashes = {}
    for source_path in code_files:
        path = (ROOT / source_path).resolve()
        try:
            relative = path.relative_to(ROOT.resolve()).as_posix()
        except ValueError as error:
            raise ValueError(f"Code snapshot must be inside the repository: {path}") from error
        if relative in code_hashes:
            raise ValueError(f"Duplicate code snapshot path: {relative}")
        content = path.read_bytes()
        snapshots[f"code/{relative}"] = content
        code_hashes[relative] = _digest(content)
        expected = summary.get("code_sha256", {}).get(relative)
        if expected is None:
            expected = summary.get("script_sha256", {}).get(path.name)
        if expected is not None and expected != code_hashes[relative]:
            raise ValueError(f"Code hash changed since evaluation: {relative}")
    metric_fields = list(dict.fromkeys(key for row in summary["metrics"] for key in row))
    contents = {
        "predictions.csv": _csv(rows, PREDICTION_FIELDS).encode("utf-8-sig"),
        "results.json": summary_json.encode("utf-8"),
        "metrics.csv": _csv(summary["metrics"], metric_fields).encode("utf-8-sig"),
        "report.md": _report(summary, reproduction_command, compatible).encode("utf-8"),
        **snapshots,
    }
    manifest = {
        **summary, "schema_version": 1, "written_at_utc": datetime.now(UTC).isoformat(),
        "reproduce_command": reproduction_command, "target_sha256": target_hash, "target_rows": target_count,
        "target_key": ["supplier", "sku", "unit", "origin", "horizon"],
        "validated_target_key": ["supplier", "warehouse", "sku", "unit", "origin", "horizon"],
        "verified_full_cohort_metric_groups": checked, "legacy_registry_compatible": compatible,
        "source_hashes": sorted(sources), "code_sha256": code_hashes,
        "code_provenance": "Captured at artifact write time; original repository-relative paths retained",
        "files": {name: {"sha256": _digest(content)} for name, content in contents.items()},
    }
    manifest["comparison_signature"] = _digest(json.dumps(
        [sorted(sources), target_hash], separators=(",", ":")
    ).encode("utf-8"))
    manifest_content = _json(manifest).encode("utf-8")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{output_dir.name}-", dir=output_dir.parent) as staging:
        staging_path = Path(staging)
        for name, content in contents.items():
            path = staging_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        # Exclusive reservation prevents concurrent writers from replacing an existing run.
        output_dir.mkdir(exist_ok=False)
        try:
            for path in staging_path.iterdir():
                path.rename(output_dir / path.name)
            # A failed write never leaves a successful-looking manifest.
            pending = output_dir / ".manifest.json.tmp"
            pending.write_bytes(manifest_content)
            pending.rename(output_dir / "manifest.json")
        except BaseException:
            shutil.rmtree(output_dir)
            raise
    return manifest
