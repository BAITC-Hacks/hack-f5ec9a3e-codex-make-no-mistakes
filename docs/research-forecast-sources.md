# Forecasting research evidence

Research date: 2026-09-23. Scope: forecasting only; no training, installations, production edits, or asserted improvements on this repository. Baseline context supplied by the coordinating researcher: capped EWMA remains competitive; SBA/TSB and bulk cleaning have not consistently improved it; global LightGBM Tweedie has modest, uneven gains and lower negative bias. All proposed choices below are hypotheses requiring the existing supplier-separated evaluation.

## Three bounded candidates

### 1. Add a distribution to the existing forecast before replacing its mean

**Proposed experiment (inference).** Keep the existing EWMA point prediction. Estimate distributions of cumulative 7-day and 28-day gross positive outgoing sales from historical complete horizon blocks, and separately test signed, out-of-fold cumulative residual calibration around EWMA. Preserve contiguous blocks to retain within-block timing/dependence. Compare recent versus longer histories using tuning origins only. Do not call this a reproduction of the more complex Willemain bootstrap. For sparse SKUs, shrink to a compatible supplier/category/scale cohort; return a low-confidence fallback for unseen items. Evaluate uncapped actual sales even if the point model uses capped inputs.

**Support.** Willemain, Smart and Schwarz (2004) forecast cumulative lead-time demand distributions using a time-series bootstrap and report greater distributional accuracy than exponential smoothing and Croston across nine industrial datasets. Their evaluation includes 1-, 3-, and 6-month lead times, not this project's 7-/28-day horizons. [Paper and abstract](https://www.sciencedirect.com/science/article/pii/S016920700300013X); [author-hosted paper](https://smartcorp.com/wp-content/uploads/2015/07/IJF_Bootstrap_paper_Smart_Software.pdf).

**Material counterevidence.** Syntetos, Babai and Gardner (2015), studying more than 7,000 series, conclude that simple parametric methods perform well and question bootstrap complexity. SES beats the tested bootstrap on backorders in the difficult electronics data. They also criticize assumptions used in the earlier paper's parametric comparisons. This directly rules out claiming that intermittent electrical-product demand makes bootstrap automatically superior. [Paper](https://www.sciencedirect.com/science/article/pii/S0148296315001496).

**Implementation/interpretation constraint.** Ordinary empirical resampling cannot invent an unseen tail; one historic project order can dominate a sparse distribution. Overlapping horizon blocks are dependent, so their count overstates independent evidence. A normalized pooled residual distribution needs as-of scaling and cohort labels and does not prove per-SKU calibration. Use exact horizon totals rather than adding marginal daily quantiles: in general the quantile of a sum is not the sum of quantiles.

**Calibration source.** Official StatsForecast provides rolling-window conformal interval tooling. The current implementation uses absolute errors and forms symmetric intervals; that is not automatically a calibrated nonnegative demand distribution or a desired one-sided replenishment quantile. For this experiment, signed cumulative residual quantiles or direct quantile calibration should be distinguished from its symmetric default. [Tutorial](https://nixtlaverse.nixtla.io/statsforecast/docs/tutorials/conformalprediction.html); [source](https://github.com/Nixtla/statsforecast/blob/main/python/statsforecast/models.py).

### 2. Extend the existing global LightGBM experiment to direct horizon quantiles

**Proposed experiment (inference).** Reuse the existing feature pipeline and split, with one small fixed set of quantile levels and direct 7-/28-day targets. Compare against candidate 1 and EWMA using pinball loss and coverage, alongside the original point metrics. Keep a Tweedie mean forecast separately: a median or upper quantile is not an unbiased mean. Repair/report quantile crossing consistently and calibrate only using pre-origin outcomes. Do not add a deep-learning dependency for this first test.

**Implementation evidence.** LightGBM officially supports `quantile` with `alpha`; its `tweedie` objective instead has a variance-power parameter. Selecting Tweedie alone does not return calibrated operational quantiles. [Official parameter documentation](https://lightgbm.readthedocs.io/en/latest/Parameters.html).

**Why global remains plausible despite uneven results.** Montero-Manso and Hyndman (2021) show that global forecasting is not inherently restricted to homogeneous series and discuss global/local complexity. This supports testing pooled learning, not claiming that any particular LightGBM feature set dominates local EWMA. [Primary preprint](https://arxiv.org/abs/2008.00444).

**Cold starts and seasonality.** Wen et al. (2017) demonstrate a multi-horizon quantile framework using temporal/static covariates across series, including cold starts and planned-event spikes. This is evidence for the information structure, not evidence that we need their recurrent architecture. For this project, use only product metadata and events known at each origin; compare new-item predictions to a transparent same-supplier/category prior and report cold-start performance separately. Annual seasonality cannot be reliably inferred from a short product history; cohort calendar effects require repeatable evidence. [Primary paper](https://arxiv.org/abs/1711.11053).

**Bulk-order constraint (project inference).** The failed raw+clean+bulk feature combination is a reason not to rerun that experiment with extra complexity. Known future project/customer orders may be scenario inputs only when recorded before the origin. Realized future bulk labels are leakage. In the absence of advance information, bulk uncertainty belongs in the predictive tail; identifying a historic large sale does not make the next one predictable.

### 3. A small temporal-aggregation challenger, not a model tournament

**Proposed experiment (inference).** Benchmark ADIDA or IMAPA, preferably whichever is already available in the research environment, with the original daily EWMA retained. Use the same raw-sales target and locked supplier/horizon splits. Inspect stable intermittent segments first; avoid large per-SKU model selection on six tuning origins. A daily/weekly aggregate combination can test whether timing noise hides a level signal without implementing a full hierarchy.

**Implementation evidence.** Official StatsForecast documents ADIDA as non-overlapping aggregation followed by simple exponential smoothing and disaggregation; IMAPA combines multiple aggregation levels. Their availability reduces implementation risk, but does not justify installing them in the backend. [ADIDA](https://nixtlaverse.nixtla.io/statsforecast/docs/models/adida.html); [IMAPA](https://nixtlaverse.nixtla.io/statsforecast/docs/models/imapa.html).

**Primary research support and limitation.** Kourentzes and Athanasopoulos (2021) motivate higher-frequency intermittent forecasts adjusted using trend/seasonal structure visible at aggregated levels. This is evidence for aggregation as a useful signal view. It is not a universal performance guarantee. Fewer aggregate observations and slower reaction to demand changes can be disadvantages here. [Paper](https://www.sciencedirect.com/science/article/pii/S0377221720304926).

## Evaluation conditions applying to all three

- Preserve separate IEK/Systeme units and supplier metrics. Report each horizon, active/new/zero-heavy/bulk-heavy segments, directional bias, and runtime. Do not pool incompatible raw quantities into a single headline score.
- Tune on July-December 2025 only. January-August 2026 has already influenced research judgment; label it retrospective evidence rather than an untouched holdout. Register decisions before genuinely unseen future evaluation.
- Quantiles: report pinball loss by level, empirical exceedance rates, and interval width with coverage. Coverage alone rewards very wide intervals. Aggregate coverage can hide severe segment failures; do not promise per-SKU coverage with a handful of origins.
- All labels must be complete before training/calibration at an origin. Daily-origin 28-day labels overlap; use horizon-aware folds and avoid treating overlapping errors as independent confidence observations.
- For level shifts, compare a short and a long calibration history chosen on tuning data; report recovery after jumps rather than blindly applying stationary calibration. Standard exchangeability-based conformal guarantees do not automatically survive dependent, shifting demand. Gibbs and Candes (2021) provide adaptive conformal machinery targeting long-run coverage under distribution shift, but that does not guarantee tight intervals, conditional SKU coverage, or instantaneous response. Do not add that machinery until a simpler rolling calibration fails clearly. [Primary NeurIPS paper](https://proceedings.neurips.cc/paper/2021/hash/0d441de75945e5acbc865406fc9a2559-Abstract.html).
- Keep sales distinct from latent demand. None of these forecasting sources resolves missing sales due to stockouts without additional availability evidence.

## Why these choices, rather than another architecture

The first candidate changes the missing output (uncertainty) while preserving a hard-to-beat point baseline; the second reuses existing global infrastructure; the third cheaply tests a different time-scale assumption. None requires believing that more complex models solve unpredictable project purchases. Probabilistic combination research reports gains but also a tradeoff between statistical accuracy and inventory performance, reinforcing the need to test decisions separately. [Wang, Kang and Petropoulos primary paper, published 2024](https://doi.org/10.1016/j.ejor.2024.01.032); [open preprint](https://arxiv.org/abs/2304.03092).
