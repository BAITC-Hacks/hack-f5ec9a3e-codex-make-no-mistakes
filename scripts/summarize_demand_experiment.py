"""Independently reconcile saved forecasts and produce the experiment report."""
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/demand-experiment"
data = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
models = ["sultan_mean59", "mean28", "weekly_ewma", "robust_ewma", "seasonal364", "seasonal_blend"]
names = ["Sultan 59d", "Mean 28d", "Weekly EWMA", "Capped EWMA", "Prior year", "Seasonal blend"]
groups = defaultdict(list)
with (OUT / "predictions.csv").open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        if row["phase"] == "holdout_2026":
            groups[(row["supplier"], row["unit"], int(row["horizon"]))].append(row)

checks = []
for (supplier, unit, horizon), rows in groups.items():
    actual = np.array([float(r["actual"]) for r in rows])
    for model in models:
        pred = np.array([float(r[model]) for r in rows])
        assert np.all(np.isfinite(pred)) and np.all(pred >= 0)
        metric = next(m for m in data["metrics"] if (m["supplier"], m["unit"], m["horizon"], m["model"], m["phase"], m["segment"]) ==
                      (supplier, unit, horizon, model, "holdout_2026", "all"))
        assert abs(np.abs(pred - actual).sum() / actual.sum() * 100 - metric["wape_pct"]) < 0.00051
        assert abs(pred.sum() - metric["predicted_qty"]) < 0.00051
    months = sorted({r["origin"] for r in rows})
    monthly = []
    for month in months:
        selected = [r for r in rows if r["origin"] == month]
        a = np.array([float(r["actual"]) for r in selected])
        b = np.array([float(r["sultan_mean59"]) for r in selected])
        c = np.array([float(r["robust_ewma"]) for r in selected])
        monthly.append([a.sum(), np.abs(b - a).sum(), np.abs(c - a).sum()])
    monthly = np.array(monthly)
    rng = np.random.default_rng(20260923)
    sample = monthly[rng.integers(0, len(months), size=(5000, len(months)))].sum(axis=1)
    improvement_pp = (sample[:, 1] - sample[:, 2]) / sample[:, 0] * 100
    ci = np.quantile(improvement_pp, [0.025, 0.975])
    checks.append({"supplier": supplier, "unit": unit, "horizon": horizon,
                   "capped_better_months": int((monthly[:, 2] < monthly[:, 1]).sum()),
                   "month_count": len(months), "paired_month_bootstrap_improvement_pp_95": ci.tolist()})

coverage = defaultdict(lambda: [0.0, 0.0])
with (OUT / "coverage.csv").open(encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        if r["origin"].startswith("2026") and r["horizon"] == "28":
            key = (r["supplier"], r["unit"])
            coverage[key][0] += float(r["eligible_qty"])
            coverage[key][1] += float(r["all_observed_qty"])

def metric(supplier, unit, model, horizon=28, segment="all"):
    return next(m for m in data["metrics"] if (m["supplier"], m["unit"], m["horizon"], m["model"], m["phase"], m["segment"]) ==
                (supplier, unit, horizon, model, "holdout_2026", segment))

lines = ["# Demand experiment results / Результаты проверки спроса", "",
         "2026-09-23. Reproduce: `python scripts/backtest_demand.py`, then `python scripts/summarize_demand_experiment.py`.", "",
         "## Вывод", "",
         "Идея Sultan применима как объяснимый базовый расчёт и черновик для менеджера. Простое среднее даёт заметные ошибки по SKU; автоматический заказ на его основе пока не обоснован. Ограничение пиков иногда уменьшает WAPE, но одновременно увеличивает недопрогноз. Нельзя выбирать метод только по абсолютной ошибке.", "",
         "## Conclusion", "",
         "Reuse Sultan's explainable demand → coverage → inventory gap → reviewed draft structure. Its historical average is a useful baseline, but these results do not justify autonomous ordering. Spike capping sometimes lowers WAPE while increasing underforecasting; the procurement decision needs an explicit shortage-versus-excess trade-off.", "",
         f"Read all 248,915 source movement rows; included 238,402 positive outgoing rows in January 2025–August 2026. Generated {data['forecast_rows']:,} SKU/origin/horizon rows across validation and holdout, each with six candidate forecasts. The held-out 28-day evaluation contains {sum(len(v) for k,v in groups.items() if k[2] == 28):,} SKU/origin rows. Unit groups are never pooled.", "",
         "Forecast origins: July–December 2025 for selection; January–August 2026 for holdout. At each origin, only prior observations are available. All four 28-day unit groups selected capped EWMA using 2025 alone. Full [methodology and limitations](DEMAND_EXPERIMENT.md).", "",
         "## 28-day held-out WAPE, % / Ошибка на 28 дней", "",
         "Lower is better. WAPE is summed absolute SKU errors divided by recorded sales; 100 − WAPE is not an accuracy score.", "",
         "| Supplier/unit | " + " | ".join(names) + " |", "|---|" + "---:|" * len(models)]
for supplier, unit in coverage:
    lines.append(f"| {supplier} / {unit} | " + " | ".join(f"{metric(supplier,unit,m)['wape_pct']:.1f}" for m in models) + " |")
lines += ["", "The prior-year comparisons performed worse on this holdout. This rejects these particular rules, not seasonality in general. They have only one usable prior year, sparse SKU histories and possible changes in assortment/availability. Do not paste September Excel seasonal/growth coefficients into past forecasts: that leaks future information.", "",
          "## Underforecasting trade-off / Риск недопрогноза", "",
          "| Supplier/unit | Sultan bias % | Capped bias % | Sultan underforecast % | Capped underforecast % |", "|---|---:|---:|---:|---:|"]
for supplier, unit in coverage:
    a, b = metric(supplier, unit, models[0]), metric(supplier, unit, "robust_ewma")
    lines.append(f"| {supplier} / {unit} | {a['bias_pct']:+.1f} | {b['bias_pct']:+.1f} | {a['underforecast_pct']:.1f} | {b['underforecast_pct']:.1f} |")
lines += ["", "Negative bias means forecast below recorded sales. Underforecast is the sum of positive actual-minus-forecast gaps across SKU targets, divided by total recorded sales. Neither metric is a stockout rate. For Systeme, capped EWMA's modest WAPE gain comes with a 25.3% aggregate underforecast and raises underforecast quantity from 23.3% to 34.0% of recorded sales.", "",
          "## Consistency and coverage / Устойчивость и охват", "",
          "| Supplier/unit | Capped beats Sultan, months / 8 | Improvement pp, bootstrap 95% interval | Mature-SKU sales coverage % | Clean-row sensitivity WAPE: Sultan / capped |", "|---|---:|---:|---:|---:|"]
for c in checks:
    if c["horizon"] != 28:
        continue
    supplier, unit = c["supplier"], c["unit"]
    lo, hi = c["paired_month_bootstrap_improvement_pp_95"]
    covered, total = coverage[(supplier, unit)]
    a = metric(supplier, unit, models[0], segment="no_ambiguous_rows_sensitivity")["wape_pct"]
    b = metric(supplier, unit, "robust_ewma", segment="no_ambiguous_rows_sensitivity")["wape_pct"]
    lines.append(f"| {supplier} / {unit} | {c['capped_better_months']} | {lo:+.1f} to {hi:+.1f} | {covered/total*100:.2f} | {a:.1f} / {b:.1f} |")
lines += ["", "Intervals use 5,000 paired resamples of the eight monthly origin blocks, fixed seed 20260923; positive improvement favors capping. Eight months is a small sample and adjacent months may be dependent. These are descriptive uncertainty estimates, not proof of significance. Coverage refers to observed sales quantity at the sampled target windows, not all SKUs or hidden demand. The clean-row subset retrospectively removes series with ambiguous/missing rows; it is a sensitivity check, not production filtering.", "",
          "## Seven-day forecasts and intermittent items", "",
          "| Supplier/unit | 7d Sultan WAPE % | 7d capped WAPE % | 28d regular Sultan WAPE % | 28d intermittent Sultan WAPE % |", "|---|---:|---:|---:|---:|"]
for supplier, unit in coverage:
    vals = [metric(supplier, unit, models[0], 7)["wape_pct"], metric(supplier, unit, "robust_ewma", 7)["wape_pct"],
            metric(supplier, unit, models[0], segment="regular")["wape_pct"], metric(supplier, unit, models[0], segment="intermittent")["wape_pct"]]
    lines.append(f"| {supplier} / {unit} | " + " | ".join(f"{v:.1f}" for v in vals) + " |")
lines += ["", "Intermittent means sales in fewer than four of the previous eight weeks. Here the Sultan baseline's intermittent WAPE exceeds 100% in every group: an always-zero forecast would score exactly 100% on these nonzero-total targets. This is a diagnostic comparison, not an operational recommendation to order nothing. Seven-day targets are only the first seven days of each sampled month; holiday/month-start effects may matter. Longer horizons are easier to forecast here, but the operational horizon must follow lead time and review cadence, not whichever metric looks best.", "",
          "## Synthetic checks / Синтетические проверки", "",
          "These are deliberately invented mechanics tests, not measured partner outcomes.", "",
          "- Stable demand of 10/day implies 280 units over 28 days. Adding one 1,000-unit sale raises Sultan's forecast to 754.6, EWMA to 1,487.2, and capped EWMA to 364.5. Capping helps but still inflates the forecast 30.2%; it is not a reliable one-off-order detector. Customer concentration remains untestable without customer IDs.",
          "- Known 14 available days out of 28 with 140 recorded sales: raw extrapolation gives 140, availability-adjusted extrapolation gives 280. This assumes a stable rate during available and unavailable days; exact availability is absent from the partner data.",
          "- Assumed demand 200, free stock 23, multiple 6: order is 60 with eligible transit 120, and 180 without transit. Unknown or negative stock raises an error rather than becoming zero.", "",
          "## What to carry into the hackathon / Что переносить", "",
          "1. **Use now:** import both suppliers, maintain warehouse/unit identity, show a simple historical baseline, explain the inventory-gap arithmetic, account for eligible transit, allow manager edits and export approved quantities.",
          "2. **Keep optional and visible:** spike flags with raw-versus-adjusted demand side by side. The cap is a hypothesis for manager review; do not silently delete large invoices or present document IDs as customer IDs.",
          "3. **Next experiment:** cost/service-aware selection and bias limits on a new validation split, plus SKU cohorts and pooled seasonal factors. Do not retune repeatedly on this 2026 holdout and keep calling it unseen data. Obtain lead-time and stockout evidence before claiming procurement savings.",
          "4. **Do not claim yet:** reliable recovered lost demand, proven customer-concentration filtering, optimized service levels, or autonomous ordering. No historical inventory simulation was performed.", "",
          "Для демонстрации: показать исходный расчёт Sultan, объяснить его ошибку на истории, затем показать изменение заказа от транзита и ограничение пика с предупреждением о недопрогнозе. Менеджер видит оба варианта и утверждает количество. Сезонность и рост остаются обязательными сценариями брифа, но эти конкретные сезонные формулы не доказали пользу; недостающие поля отмечаем как допущения.", "",
          "## Evidence", "",
          "- [Machine-readable metrics and source hashes](../artifacts/demand-experiment/results.json)",
          "- [Metrics CSV](../artifacts/demand-experiment/metrics.csv)",
          "- [Monthly metrics](../artifacts/demand-experiment/monthly_metrics.csv)",
          "- [Per-SKU forecasts](../artifacts/demand-experiment/predictions.csv)",
          "- [Coverage](../artifacts/demand-experiment/coverage.csv)",
          "- [Consistency diagnostics](../artifacts/demand-experiment/diagnostics.json)", "",
          "Verification: saved forecasts independently reconcile to every held-out headline WAPE and predicted total; predictions are finite/nonnegative. Source row counts match the existing audit. Embedded checks cover constant/zero histories, isolation from future observations, stock/transit/multiple arithmetic, missing-stock rejection and known-availability arithmetic."]
(ROOT / "docs/DEMAND_RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
(OUT / "diagnostics.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"reconciled_groups": len(groups), "diagnostics_28d": [c for c in checks if c["horizon"] == 28]}, ensure_ascii=True))
