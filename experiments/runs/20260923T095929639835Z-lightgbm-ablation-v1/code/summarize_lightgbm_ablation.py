"""Verify the full-feature control and write the B2 experiment report."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/lightgbm-ablation"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    summary = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
    key = lambda r: tuple(r[k] for k in ("supplier", "sku", "unit", "origin", "horizon"))
    old = {key(r): r for r in read_csv(ROOT / "artifacts/lightgbm-experiment/candidate_predictions.csv")}
    new = read_csv(OUT / "candidate_predictions.csv")
    assert len(new) == len(old) == 65754
    assert {key(r) for r in new} == set(old)
    for row in new:
        prior = old[key(row)]
        assert row["actual"] == prior["actual"]
        assert float(row["tweedie_full"]) == float(prior["lgbm_tweedie"]), key(row)
    training = read_csv(OUT / "training.csv")
    assert len(training) == 448
    assert all(r["last_label_end_exclusive"] <= r["origin"] for r in training)
    metrics = summary["metrics"]
    groups = sorted({(m["supplier"], m["unit"], m["horizon"]) for m in metrics})
    lookup = {(m["phase"], m["supplier"], m["unit"], m["horizon"], m["model"], m["segment"]): m for m in metrics}
    models = list(summary["candidates"])
    selections = {(s["supplier"], s["unit"], s["horizon"]): s["model"] for s in summary["selections"]}
    for group in groups:
        expected = min(models, key=lambda m: lookup[("development_2025", *group, m, "all")]["wape_pct"])
        assert selections[group] == expected
    lines = ["# LightGBM feature ablation (B2)", "", "Owner: @dimashisenov. Run date: 2026-09-23.", "",
             "## Protocol", "",
             "Predeclared in [issue #4](https://github.com/BAITC-Hacks/hack-f5ec9a3e-codex-make-no-mistakes/issues/4#issuecomment-5792732946). "
             "Hypothesis: removing feature groups may generalize better on short histories. Keep the v1 Tweedie objective (power 1.5), "
             "150 rounds, 15 leaves, learning rate 0.05, seed, examples and targets unchanged. Compare full (29 features), "
             "no SKU (28), no calendar (25), and no individual weekly lags (21). All remaining recency and rolling features stay. "
             "Selection among four variants uses total 2025 development WAPE separately per supplier/unit/horizon. "
             "The baseline remains a separate decision comparator. 2026 is already-viewed retrospective data. "
             "This follow-up was motivated by prior results, and is not independent confirmation or a new holdout.", "",
             "## WAPE results (%)", "", "Lower is better. Selected means the 2025-selected ablation, not the best retrospective score.", ""]
    for phase in ("development_2025", "retrospective_2026"):
        lines += [f"### {phase}", "", "| Supplier / unit / days | Baseline | Full | No SKU | No calendar | No week lags | Selected |", "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
        for group in groups:
            values = [lookup[(phase, *group, m, "all")]["wape_pct"] for m in ["baseline_selected", *models]]
            lines.append("| " + " / ".join(map(str, group)) + " | " + " | ".join(f"{v:.3f}" for v in values) + f" | {selections[group]} |")
        lines.append("")
    lines += ["## Retrospective bias and sparse errors", "", "Negative bias means aggregate underprediction; it can hide offsetting errors. Underforecast is not a stockout rate.", "",
              "| Supplier / unit / days | Baseline bias | Selected bias | Baseline underforecast | Selected underforecast | Baseline sparse WAPE | Selected sparse WAPE |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for group in groups:
        b = lookup[("retrospective_2026", *group, "baseline_selected", "all")]
        s = lookup[("retrospective_2026", *group, "lgbm_selected", "all")]
        values = [b["bias_pct"], s["bias_pct"], b["underforecast_pct"], s["underforecast_pct"],
                  lookup[("retrospective_2026", *group, "baseline_selected", "intermittent")]["wape_pct"],
                  lookup[("retrospective_2026", *group, "lgbm_selected", "intermittent")]["wape_pct"]]
        lines.append("| " + " / ".join(map(str, group)) + " | " + " | ".join(f"{v:.3f}" for v in values) + " |")
    lines += ["", "## Verification and reproduction", "",
              f"Full-feature control exactly reproduces all {len(new):,} v1 Tweedie predictions and actuals. "
              f"All {len(training)} training label cutoffs passed; every selected variant matches the development-only rule. "
              f"Runtime: {summary['elapsed_seconds']:.2f} seconds total, {summary['fit_predict_seconds']:.2f} seconds fitting/predicting. "
              "Environment is pinned in experiments/requirements.txt; detailed environment and hashes are in the run summary.", "",
              "```sh", "experiments/.venv/Scripts/python.exe scripts/backtest_lightgbm.py --ablation",
              "python scripts/summarize_lightgbm_ablation.py", "```", "",
              "Run the baseline and v1 LightGBM first if their local artifacts are absent; see [workflow](../experiments/README.md). "
              "Raw predictions, monthly metrics, feature importance and training cutoffs are in artifacts/lightgbm-ablation. "
              "Register this directory to freeze the run. Published summaries are linked from [the comparison table](../experiments/INDEX.md); "
              "large CSV archives remain local. No production model or purchasing policy is changed.", ""]
    (ROOT / "docs/LIGHTGBM_ABLATION.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Verified {len(new)} exact control predictions and {len(training)} training cutoffs; report written")


if __name__ == "__main__":
    main()
