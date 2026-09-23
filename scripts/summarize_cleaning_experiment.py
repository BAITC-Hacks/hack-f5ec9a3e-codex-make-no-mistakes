"""Verify the paired control and generate the issue #3 result readout from artifacts."""
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    clean_dir = ROOT / "artifacts/demand-cleaning"
    lgb_dir = ROOT / "artifacts/lightgbm-cleaning"
    clean = json.loads((clean_dir / "results.json").read_text(encoding="utf-8"))
    lgb = json.loads((lgb_dir / "results.json").read_text(encoding="utf-8"))
    key = lambda r: tuple(r[k] for k in ("supplier", "sku", "unit", "origin", "horizon"))
    original = {key(r): r for r in read_csv(ROOT / "artifacts/lightgbm-experiment/candidate_predictions.csv")}
    paired = read_csv(lgb_dir / "candidate_predictions.csv")
    assert len(original) == len(paired) == clean["rows"] == lgb["rows"] == 65754
    assert {key(r) for r in paired} == set(original)
    for row in paired:
        old = original[key(row)]
        for new_name, old_name in (("actual", "actual"), ("tweedie_raw", "lgbm_tweedie"),
                                   ("baseline_selected", "baseline_selected")):
            assert float(row[new_name]) == float(old[old_name]), (key(row), new_name)
    training = read_csv(lgb_dir / "training.csv")
    assert len(training) == 224
    assert all(r["last_label_end_exclusive"] <= r["origin"] for r in training)
    runs = {}
    for path in sorted((ROOT / "experiments/runs").glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["name"] in ("demand-cleaning-v1", "lightgbm-cleaning-v1"):
            runs[manifest["name"]] = manifest
    assert len(runs) == 2
    assert len({r["comparison_signature"] for r in runs.values()}) == 1
    metrics = clean["metrics"] + lgb["metrics"]
    lookup = {(m["phase"], m["supplier"], m["unit"], m["horizon"], m["segment"], m["model"]): m
              for m in metrics}
    groups = sorted({(m["supplier"], m["unit"]) for m in metrics})
    lines = ["# Demand cleaning results / Результаты очистки спроса", "",
             "Reproduce this readout: `experiments/.venv/Scripts/python.exe scripts/summarize_cleaning_experiment.py`.",
             "Policy and reproduction: [DEMAND_CLEANING.md](DEMAND_CLEANING.md).", "",
             "## Decision", "",
             "Keep the explainable cleaning policy and review artifacts, but do not enable automatic bulk exclusion "
             "as the default forecast input. On the 28-day benchmark the cleaned baseline loses in every "
             "supplier/unit group in both development and retrospective evaluation. Removing plausible bulk "
             "orders can remove recurring demand and increase underforecasting. LightGBM results below isolate "
             "feature cleaning with unchanged raw training labels; any gains are specific to those groups.", "",
             "There IS a consistent short-horizon WAPE improvement: holding the original baseline models "
             "fixed, cleaning improves all four groups at 7 days in both 2025 and 2026. In 2026 the reductions "
             "range from 0.486 to 5.671 percentage points. However, underforecast ratios rise in every group; "
             "for IEK packs they rise from 34.172% to 45.230%. Keep this as an optional 7-day experiment, "
             "not evidence of better stock availability or a reason to enable cleaning for all horizons.", "",
             "The useful 28-day LightGBM gain is IEK packs: WAPE improves from 46.293% to 44.515% "
             "in 2026, but the existing baseline remains better at 42.567%. IEK pieces are nearly flat, "
             "while IEK meters and Systeme are slightly worse. The packs improvement is not an overall "
             "new best forecast, and the tiny development gain for IEK pieces does not carry into 2026.", "",
             "Synthetic acceptance checks retain a steady 10-unit/day series after adding one 1,000-unit order "
             "and preserve sustained 2x and 10x growth once three elevated days are visible. This establishes "
             "mechanics, not real customer intent. Recent flags can be revised as growth evidence arrives.", "",
             "## Data and validation", "",
             "Two original transaction workbooks; Алматы; January 2025–August 2026; exact SKU/unit separation. "
             "All 65,754 forecast keys and raw actuals are unchanged. July–December 2025 chooses models; "
             "January–August 2026 is already-known retrospective evidence, not a fresh test. "
             "No customer IDs or exact availability intervals were supplied.", "",
             "The paired raw LightGBM control exactly reproduces all 65,754 earlier Tweedie predictions, "
             "actuals and baseline forecasts. All 224 model fits have training labels ending no later than "
             "their forecast origin. The experiment register independently checks exported predictions and "
             "full-cohort WAPE, bias, underforecasting and MAE. Source hashes and target signatures match.", "",
             f"Baseline/cleaning runtime: {clean['elapsed_seconds']:.1f}s; paired LightGBM runtime: "
             f"{lgb['elapsed_seconds']:.1f}s (includes preprocessing).", "",
             "## Cleaning evidence", "",
             "Full-source classification includes 248,915 movement rows plus two report-total footer rows "
             "quarantined for missing identity/date. The 417 negative rows remain unresolved; "
             "31 missing quantities remain missing. These counts cover the full source, including dates "
             "outside the experiment. The experiment uses 238,402 positive source lines.", "",
             "Final-cutoff document decisions (2026-09-01):", "",
             "| Reason | Orders |", "| --- | ---: |"]
    for reason, count in clean["order_reasons"].items():
        lines.append(f"| {reason} | {count:,} |")
    totals = defaultdict(lambda: [0, 0, 0.0, 0.0])
    for row in read_csv(clean_dir / "order_decisions.csv"):
        values = totals[(row["supplier"], row["unit"])]
        values[0] += 1
        values[1] += float(row["excluded_quantity"]) > 0
        values[2] += float(row["original_quantity"])
        values[3] += float(row["excluded_quantity"])
    lines += ["", "| Supplier / unit | Orders | Flagged | Flagged % | Raw quantity | Excluded quantity | Excluded % |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for (supplier, unit), (n, flags, raw, removed) in sorted(totals.items()):
        lines.append(f"| {supplier} / {unit} | {n:,} | {flags:,} | {100*flags/n:.2f} | {raw:,.1f} | "
                     f"{removed:,.1f} | {100*removed/raw:.2f} |")
    lines += ["", "Bulk flags are candidates, not confirmed errors. Missing days represent zero recorded sales, "
              "not known zero underlying demand. The final-cutoff cleaned CSV is not valid input to earlier "
              "backtests; each historical origin recomputes its own cleaning."]
    models = ["baseline_selected", "clean_fixed_baseline", "clean_selected", "tweedie_raw", "tweedie_clean"]
    for horizon in (28, 7):
        for phase in ("development_2025", "retrospective_2026"):
            lines += ["", f"## {horizon}-day WAPE (%), {phase}", "",
                      "Lower is better. `clean_fixed_baseline` holds the original model choice fixed; "
                      "`clean_selected` reselects among the same four baseline methods using 2025 only.", "",
                      "| Supplier / unit | Baseline | Clean fixed | Clean selected | Tweedie raw | Tweedie clean | Clean−raw Tweedie (pp) |",
                      "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
            for supplier, unit in groups:
                values = [lookup[(phase, supplier, unit, horizon, "all", m)]["wape_pct"] for m in models]
                lines.append(f"| {supplier} / {unit} | " + " | ".join(f"{v:.3f}" for v in values)
                             + f" | {values[-1]-values[-2]:+.3f} |")
    lines += ["", "## Bias and failure cases (28-day, retrospective 2026)", "",
              "Negative bias means underforecasting. Underforecast ratio is missed forecast quantity divided "
              "by raw sales; it is not an inventory stockout rate.", "",
              "| Supplier / unit | Model | Bias % | Underforecast % | Regular WAPE % | Intermittent WAPE % |",
              "| --- | --- | ---: | ---: | ---: | ---: |"]
    for supplier, unit in groups:
        for model in models:
            values = lookup[("retrospective_2026", supplier, unit, 28, "all", model)]
            segments = [lookup[("retrospective_2026", supplier, unit, 28, segment, model)]["wape_pct"]
                        for segment in ("regular", "intermittent")]
            lines.append(f"| {supplier} / {unit} | {model} | {values['bias_pct']:.3f} | "
                         f"{values['underforecast_pct']:.3f} | {segments[0]:.3f} | {segments[1]:.3f} |")
    monthly = read_csv(lgb_dir / "monthly_metrics.csv")
    lines += ["", "## Monthly stability (paired Tweedie, 28-day)", "",
              "| Supplier / unit | Better months in 2025 / 6 | Better months in 2026 / 8 |",
              "| --- | ---: | ---: |"]
    for supplier, unit in groups:
        counts = []
        for year in ("2025", "2026"):
            values = {(r["origin"], r["model"]): float(r["wape_pct"]) for r in monthly
                      if r["supplier"] == supplier and r["unit"] == unit and r["horizon"] == "28"
                      and r["origin"].startswith(year) and r["wape_pct"]}
            origins = {o for o, _ in values}
            counts.append(sum(values[(o, "tweedie_clean")] < values[(o, "tweedie_raw")] for o in origins))
        lines.append(f"| {supplier} / {unit} | {counts[0]} / 6 | {counts[1]} / 8 |")
    lines += ["", "## Model choice using 2025 only", "",
              "These choices compare the two fixed Tweedie variants only; they do not override a stronger "
              "baseline or establish statistical significance. Cleaning thresholds were not retuned.", "",
              "| Supplier / unit | Horizon | Selected variant |", "| --- | ---: | --- |"]
    for selection in lgb["selections"]:
        lines.append(f"| {selection['supplier']} / {selection['unit']} | {selection['horizon']} | {selection['model']} |")
    lines += ["", "## Registered runs and inspectable evidence", ""]
    for name, run in runs.items():
        lines.append(f"- [{name}](../experiments/runs/{run['run_id']}/manifest.json): "
                     f"{run['target_rows']:,} targets; {run['verified_full_cohort_metric_groups']} independently verified metric groups.")
    lines += ["", "Detailed predictions, monthly scores and exclusion ledgers are in the two local artifact "
              "directories documented in the policy. Compact JSON summaries and source/code hashes are in the "
              "registered runs. Large CSV archives remain local and Git-ignored.", "",
              "## Русский", "",
              "Очистка воспроизводима, исходники и причины исключений сохранены. Синтетические проверки "
              "разового заказа и устойчивого роста проходят. На 7 днях WAPE базовых моделей улучшился во всех "
              "группах, но доля недопрогноза выросла. На 28 днях очищенные базовые прогнозы ухудшили WAPE "
              "на горизонте 28 дней во всех четырёх группах и увеличили недопрогноз. Автоматическое исключение "
              "не включаем по умолчанию; флаги полезны для проверки документов. Таблицы LightGBM показывают "
              "отдельный эффект очистки признаков при неизменных исходных целях. 2026 — ретроспектива, "
              "а семантика возвратов и клиентская концентрация требуют дополнительных данных.", ""]
    (ROOT / "docs/DEMAND_CLEANING_RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print("PASS: exact raw control, unchanged targets, 224 temporal cutoffs; report generated")


if __name__ == "__main__":
    main()
