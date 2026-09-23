"""Verify the combined forecast control and generate its comparison from saved metrics."""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/lightgbm-combined"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def identity(row):
    return tuple(row[key] for key in ("supplier", "sku", "unit", "origin", "horizon"))


def metric_key(row):
    return tuple(row[key] for key in ("phase", "supplier", "unit", "horizon", "segment", "model"))


def main():
    result = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
    clean = json.loads((ROOT / "artifacts/lightgbm-cleaning/results.json").read_text(encoding="utf-8"))
    raw_rows = read_csv(ROOT / "artifacts/lightgbm-experiment/candidate_predictions.csv")
    raw = {identity(row): row for row in raw_rows}
    new = read_csv(OUT / "candidate_predictions.csv")
    assert len(new) == len(raw) == len(raw_rows) == result["rows"] == 65754
    assert {identity(row) for row in new} == set(raw)
    for row in new:
        old = raw[identity(row)]
        for current, previous in (
            ("actual", "actual"),
            ("tweedie_raw", "lgbm_tweedie"),
            ("baseline_selected", "baseline_selected"),
        ):
            assert float(row[current]) == float(old[previous]), (identity(row), current)
        assert row["segment"] == old["segment"]
    assert [(s["supplier"], s["sha256"]) for s in result["source_files"]] == [
        (s["supplier"], s["sha256"]) for s in clean["source_files"]
    ]
    training = read_csv(OUT / "training.csv")
    assert len(training) == 224
    assert all(row["last_label_end_exclusive"] <= row["origin"] for row in training)
    metrics = {metric_key(row): row for row in clean["metrics"] + result["metrics"]}
    groups = sorted({(row["supplier"], row["unit"], row["horizon"]) for row in result["metrics"]})
    dev, retro = "development_2025", "retrospective_2026"

    def metric(phase, group, model, name="wape_pct", segment="all"):
        return metrics[(phase, *group, segment, model)][name]

    def wins(phase, model, comparison):
        return sum(metric(phase, group, model) < metric(phase, group, comparison) for group in groups)

    selections = {(r["supplier"], r["unit"], r["horizon"]): r["model"] for r in result["forecast_selections"]}
    # Verify each saved policy actually selects solely by development scores.
    for group in groups:
        expected = min(
            ("baseline_selected", "tweedie_raw", "tweedie_combined"),
            key=lambda model: metric(dev, group, model),
        )
        assert selections[group] == expected
    for row in new:
        group = (row["supplier"], row["unit"], int(row["horizon"]))
        assert row["forecast_selected"] == row[selections[group]]
    lines = [
        "# Combined forecast results / Результаты прогноза с совместными признаками",
        "",
        "[Fixed protocol](COMBINED_FORECAST_EXPERIMENT.md) · "
        "[All registered experiments](../experiments/INDEX.md).",
        "",
        "## Answer",
        "",
        f"Adding cleaned history and bulk-order signals to the raw model improves WAPE versus raw-only "
        f"Tweedie in **{wins(dev, 'tweedie_combined', 'tweedie_raw')}/8 development groups** and "
        f"**{wins(retro, 'tweedie_combined', 'tweedie_raw')}/8 retrospective groups**. "
        "Each group is a supplier/unit/horizon combination; these are not independent statistical trials.",
        "",
        "The combined model is chosen in "
        f"**{sum(m == 'tweedie_combined' for m in selections.values())}/8 groups** "
        "when compared with the existing baseline and raw Tweedie using 2025 only. "
        "That frozen policy improves on the baseline in "
        f"**{wins(retro, 'forecast_selected', 'baseline_selected')}/8** "
        "2026 groups. All regressions are shown; no 2026 result changes the choices.",
        "",
        "Lower forecast error is not evidence of reduced stockouts or inventory savings. Inspect bias and "
        "underforecasting before using a candidate for ordering. Keep any improvement scoped to its "
        "supplier, unit and horizon; do not replace every forecast with a single winner.",
        "",
        "## What changed and what was checked",
        "",
        "The combined model has 59 features: all 29 raw features, 17 cleaned-history features and 13 "
        "bulk-order frequency/size/recency signals. The 150-round Tweedie settings, cleaning policy, "
        "sources, training labels and evaluation targets are unchanged. Raw sales remain the target.",
        "",
        "The raw control exactly reproduces all 65,754 earlier predictions, actual quantities, baseline "
        "predictions and segment labels. All 224 fits use labels observed by their forecast date. "
        "Feature checks preserve the raw block, verify hand-calculated bulk signals and reject future "
        "orders. Cached versus prefix-only cleaning and bulk signals match at training/test boundaries.",
        "",
        f"Total runtime: {result['elapsed_seconds']:.1f}s; model fit/predict: "
        f"{result['fit_predict_seconds']:.1f}s. 2025 development: July–December; 2026 retrospective: "
        "January–August. All targets are gross positive outgoing sales in Алматы, with at least 90 days "
        "since the first observed sale. Units are scored separately. The 2026 period was already seen "
        "in earlier experiments and is not an untouched test.",
        "",
    ]
    for phase in (dev, retro):
        for horizon in (7, 28):
            lines += [
                f"## {horizon}-day WAPE (%), {phase}",
                "",
                "Lower is better.",
                "",
                "| Supplier / unit | Baseline | Raw Tweedie | Clean-only | Combined | Combined−raw (pp) |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
            for group in groups:
                if group[2] != horizon:
                    continue
                values = [
                    metric(phase, group, m)
                    for m in ("baseline_selected", "tweedie_raw", "tweedie_clean", "tweedie_combined")
                ]
                lines.append(
                    f"| {group[0]} / {group[1]} | "
                    + " | ".join(f"{v:.3f}" for v in values)
                    + f" | {values[-1] - values[1]:+.3f} |"
                )
            lines.append("")
    lines += [
        "## Frozen 2025-only choice",
        "",
        "Candidates: existing baseline selection, raw Tweedie, combined Tweedie. "
        "Other historical experiments are shown in the registry, not silently added to this selection.",
        "",
        "| Supplier / unit | Days | Choice | 2026 WAPE | Δ vs baseline (pp) | Bias % | Underforecast % |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for group in groups:
        model = selections[group]
        value = metric(retro, group, model)
        delta = value - metric(retro, group, "baseline_selected")
        lines.append(
            f"| {group[0]} / {group[1]} | {group[2]} | {model} | {value:.3f} | {delta:+.3f} | "
            f"{metric(retro, group, model, 'bias_pct'):.3f} | "
            f"{metric(retro, group, model, 'underforecast_pct'):.3f} |"
        )
    lines += [
        "",
        "## Combined-model failure cases and stability",
        "",
        "All changes below compare combined features with raw-only Tweedie in 2026. "
        "Positive WAPE/underforecast deltas are worse. Negative bias indicates underforecasting.",
        "",
        "| Supplier / unit | Days | Regular WAPE Δ | Intermittent WAPE Δ | Bias raw→combined | "
        "Underforecast Δ (pp) | Better months / 8 |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    monthly = read_csv(OUT / "monthly_metrics.csv")
    for group in groups:
        changes = [
            metric(retro, group, "tweedie_combined", segment=segment)
            - metric(retro, group, "tweedie_raw", segment=segment)
            for segment in ("regular", "intermittent")
        ]
        values = {
            (r["origin"], r["model"]): float(r["wape_pct"])
            for r in monthly
            if (r["supplier"], r["unit"], int(r["horizon"])) == group
            and r["origin"].startswith("2026")
            and r["wape_pct"]
        }
        origins = {origin for origin, _ in values}
        better = sum(values[(o, "tweedie_combined")] < values[(o, "tweedie_raw")] for o in origins)
        under = metric(retro, group, "tweedie_combined", "underforecast_pct")
        under -= metric(retro, group, "tweedie_raw", "underforecast_pct")
        lines.append(
            f"| {group[0]} / {group[1]} | {group[2]} | {changes[0]:+.3f} | {changes[1]:+.3f} | "
            f"{metric(retro, group, 'tweedie_raw', 'bias_pct'):.3f} → "
            f"{metric(retro, group, 'tweedie_combined', 'bias_pct'):.3f} | {under:+.3f} | {better} / 8 |"
        )
    lines += [
        "",
        "## Evidence and reproduction",
        "",
        "Run `experiments/.venv/Scripts/python.exe scripts/backtest_lightgbm.py --combined`, "
        "register the run, then regenerate this readout with "
        "`experiments/.venv/Scripts/python.exe scripts/summarize_combined_forecast.py`.",
        "",
    ]
    manifests = []
    for path in sorted((ROOT / "experiments/runs").glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["name"] == "lightgbm-combined-v1":
            manifests.append((path, manifest))
    assert manifests, "Register the completed run before generating the final readout"
    path, manifest = manifests[-1]
    lines += [
        f"Registered run: [{manifest['run_id']}](../{path.relative_to(ROOT).as_posix()}). "
        f"The registry independently verified {manifest['verified_full_cohort_metric_groups']} "
        "full-cohort metric groups from predictions. Source/code hashes, settings and compact metrics "
        "are in the snapshot; large prediction archives remain local and Git-ignored.",
        "",
        "Working outputs: `artifacts/lightgbm-combined/` contains predictions, monthly/segment metrics, "
        "training cutoffs, feature importance, selected models and runtime provenance. "
        "The clean-only comparison requires the preceding `artifacts/lightgbm-cleaning` run.",
        "",
        "## Русский",
        "",
        "Проверили совместные признаки: исходные продажи, очищенная история и частота/размер крупных "
        "заказов. Будущие продажи не очищались; исходный контроль воспроизведён точно. Выбор модели "
        "отдельно для поставщика, единицы и горизонта — только по 2025. Таблицы показывают все улучшения "
        "и ухудшения 2026, смещение, недопрогноз и помесячную устойчивость. Это ретроспективная проверка "
        "прогноза, не доказательство экономии запасов.",
        "",
    ]
    (ROOT / "docs/COMBINED_FORECAST_RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "control": "exact",
                "rows": len(new),
                "fits": len(training),
                "development_wins_vs_raw": wins(dev, "tweedie_combined", "tweedie_raw"),
                "retrospective_wins_vs_raw": wins(retro, "tweedie_combined", "tweedie_raw"),
                "retrospective_selected_wins_vs_baseline": wins(
                    retro, "forecast_selected", "baseline_selected"
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
