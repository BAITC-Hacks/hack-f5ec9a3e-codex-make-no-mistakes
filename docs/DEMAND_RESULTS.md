# Demand experiment results / Результаты проверки спроса

2026-09-23. Reproduce: `python scripts/backtest_demand.py`, then `python scripts/summarize_demand_experiment.py`.

## Вывод

Идея Sultan применима как объяснимый базовый расчёт и черновик для менеджера. Простое среднее даёт заметные ошибки по SKU; автоматический заказ на его основе пока не обоснован. Ограничение пиков иногда уменьшает WAPE, но одновременно увеличивает недопрогноз. Нельзя выбирать метод только по абсолютной ошибке.

## Conclusion

Reuse Sultan's explainable demand → coverage → inventory gap → reviewed draft structure. Its historical average is a useful baseline, but these results do not justify autonomous ordering. Spike capping sometimes lowers WAPE while increasing underforecasting; the procurement decision needs an explicit shortage-versus-excess trade-off.

Read all 248,915 source movement rows; included 238,402 positive outgoing rows in January 2025–August 2026. Generated 65,754 SKU/origin/horizon rows across validation and holdout, each with six candidate forecasts. The held-out 28-day evaluation contains 20,098 SKU/origin rows. Unit groups are never pooled.

Forecast origins: July–December 2025 for selection; January–August 2026 for holdout. At each origin, only prior observations are available. All four 28-day unit groups selected capped EWMA using 2025 alone. Full [methodology and limitations](DEMAND_EXPERIMENT.md).

## 28-day held-out WAPE, % / Ошибка на 28 дней

Lower is better. WAPE is summed absolute SKU errors divided by recorded sales; 100 − WAPE is not an accuracy score.

| Supplier/unit | Sultan 59d | Mean 28d | Weekly EWMA | Capped EWMA | Prior year | Seasonal blend |
|---|---:|---:|---:|---:|---:|---:|
| IEK / м | 66.0 | 76.4 | 70.1 | 65.0 | 92.3 | 72.0 |
| IEK / упак | 51.2 | 53.7 | 51.3 | 42.6 | 70.2 | 59.4 |
| IEK / шт | 42.3 | 46.7 | 43.1 | 40.2 | 75.5 | 57.4 |
| Systeme electric / шт | 44.2 | 42.6 | 43.1 | 42.8 | 69.8 | 57.2 |

The prior-year comparisons performed worse on this holdout. This rejects these particular rules, not seasonality in general. They have only one usable prior year, sparse SKU histories and possible changes in assortment/availability. Do not paste September Excel seasonal/growth coefficients into past forecasts: that leaks future information.

## Underforecasting trade-off / Риск недопрогноза

| Supplier/unit | Sultan bias % | Capped bias % | Sultan underforecast % | Capped underforecast % |
|---|---:|---:|---:|---:|
| IEK / м | -3.5 | -22.7 | 34.8 | 43.8 |
| IEK / упак | +3.7 | -12.3 | 23.8 | 27.4 |
| IEK / шт | -0.1 | -10.4 | 21.2 | 25.3 |
| Systeme electric / шт | -2.4 | -25.3 | 23.3 | 34.0 |

Negative bias means forecast below recorded sales. Underforecast is the sum of positive actual-minus-forecast gaps across SKU targets, divided by total recorded sales. Neither metric is a stockout rate. For Systeme, capped EWMA's modest WAPE gain comes with a 25.3% aggregate underforecast and raises underforecast quantity from 23.3% to 34.0% of recorded sales.

## Consistency and coverage / Устойчивость и охват

| Supplier/unit | Capped beats Sultan, months / 8 | Improvement pp, bootstrap 95% interval | Mature-SKU sales coverage % | Clean-row sensitivity WAPE: Sultan / capped |
|---|---:|---:|---:|---:|
| IEK / шт | 5 | -0.1 to +4.7 | 99.74 | 45.6 / 43.1 |
| IEK / м | 4 | -3.2 to +6.8 | 99.99 | 64.1 / 65.0 |
| IEK / упак | 7 | +3.5 to +14.8 | 99.91 | 53.1 / 43.0 |
| Systeme electric / шт | 4 | -5.7 to +12.0 | 99.37 | 44.7 / 42.9 |

Intervals use 5,000 paired resamples of the eight monthly origin blocks, fixed seed 20260923; positive improvement favors capping. Eight months is a small sample and adjacent months may be dependent. These are descriptive uncertainty estimates, not proof of significance. Coverage refers to observed sales quantity at the sampled target windows, not all SKUs or hidden demand. The clean-row subset retrospectively removes series with ambiguous/missing rows; it is a sensitivity check, not production filtering.

## Seven-day forecasts and intermittent items

| Supplier/unit | 7d Sultan WAPE % | 7d capped WAPE % | 28d regular Sultan WAPE % | 28d intermittent Sultan WAPE % |
|---|---:|---:|---:|---:|
| IEK / м | 98.7 | 92.7 | 62.3 | 112.5 |
| IEK / упак | 82.0 | 73.3 | 47.7 | 122.3 |
| IEK / шт | 76.3 | 71.9 | 38.6 | 121.0 |
| Systeme electric / шт | 83.9 | 73.7 | 42.0 | 105.9 |

Intermittent means sales in fewer than four of the previous eight weeks. Here the Sultan baseline's intermittent WAPE exceeds 100% in every group: an always-zero forecast would score exactly 100% on these nonzero-total targets. This is a diagnostic comparison, not an operational recommendation to order nothing. Seven-day targets are only the first seven days of each sampled month; holiday/month-start effects may matter. Longer horizons are easier to forecast here, but the operational horizon must follow lead time and review cadence, not whichever metric looks best.

## Synthetic checks / Синтетические проверки

These are deliberately invented mechanics tests, not measured partner outcomes.

- Stable demand of 10/day implies 280 units over 28 days. Adding one 1,000-unit sale raises Sultan's forecast to 754.6, EWMA to 1,487.2, and capped EWMA to 364.5. Capping helps but still inflates the forecast 30.2%; it is not a reliable one-off-order detector. Customer concentration remains untestable without customer IDs.
- Known 14 available days out of 28 with 140 recorded sales: raw extrapolation gives 140, availability-adjusted extrapolation gives 280. This assumes a stable rate during available and unavailable days; exact availability is absent from the partner data.
- Assumed demand 200, free stock 23, multiple 6: order is 60 with eligible transit 120, and 180 without transit. Unknown or negative stock raises an error rather than becoming zero.

## What to carry into the hackathon / Что переносить

1. **Use now:** import both suppliers, maintain warehouse/unit identity, show a simple historical baseline, explain the inventory-gap arithmetic, account for eligible transit, allow manager edits and export approved quantities.
2. **Keep optional and visible:** spike flags with raw-versus-adjusted demand side by side. The cap is a hypothesis for manager review; do not silently delete large invoices or present document IDs as customer IDs.
3. **Next experiment:** cost/service-aware selection and bias limits on a new validation split, plus SKU cohorts and pooled seasonal factors. Do not retune repeatedly on this 2026 holdout and keep calling it unseen data. Obtain lead-time and stockout evidence before claiming procurement savings.
4. **Do not claim yet:** reliable recovered lost demand, proven customer-concentration filtering, optimized service levels, or autonomous ordering. No historical inventory simulation was performed.

Для демонстрации: показать исходный расчёт Sultan, объяснить его ошибку на истории, затем показать изменение заказа от транзита и ограничение пика с предупреждением о недопрогнозе. Менеджер видит оба варианта и утверждает количество. Сезонность и рост остаются обязательными сценариями брифа, но эти конкретные сезонные формулы не доказали пользу; недостающие поля отмечаем как допущения.

## Evidence

- [Machine-readable metrics and source hashes](../artifacts/demand-experiment/results.json)
- [Metrics CSV](../artifacts/demand-experiment/metrics.csv)
- [Monthly metrics](../artifacts/demand-experiment/monthly_metrics.csv)
- [Per-SKU forecasts](../artifacts/demand-experiment/predictions.csv)
- [Coverage](../artifacts/demand-experiment/coverage.csv)
- [Consistency diagnostics](../artifacts/demand-experiment/diagnostics.json)

Verification: saved forecasts independently reconcile to every held-out headline WAPE and predicted total; predictions are finite/nonnegative. Source row counts match the existing audit. Embedded checks cover constant/zero histories, isolation from future observations, stock/transit/multiple arithmetic, missing-stock rejection and known-availability arithmetic.
