# Replenishment research and next experiments

23 September 2026. **Recommendation: keep the explainable, manager-reviewed engine; modify its evaluation and uncertainty handling; investigate a narrowly scoped quantile challenger. Do not replace the live forecast from these results.**

The strongest immediate improvement is to measure the exact application policy at its purchasing horizon and establish trustworthy stock, receipt and unit inputs. Existing forecasts are useful draft inputs, but neither forecast research nor application arithmetic establishes reduced stockouts or inventory savings.

Follow-up: [experiment 1 results](APPLICATION_BASELINE_RESULTS.md) now verify the exact application callable against read-only PostgreSQL data at 7/21/28 days. The original research audit below predates that run; its no-database-access statement describes that audit only.

Follow-up: [experiment 2 results](BUFFER_CALIBRATION_RESULTS.md) reject the tested pooled q90 buffer as a general replacement: coverage improves, but three groups' pinball loss and synthetic inventory investment worsen. Compact metrics and run manifests are published with these reports; prediction archives remain local.

## Scope and evidence

This report is isolated on `codex/replenishment-research` in `C:/Users/User/Desktop/hackathon-research`, created from `0cdeb56`. Existing uncommitted work was read in place, not copied over or changed. Research evidence comes from the main checkout; application behavior comes from the requested `hackathon-replenishment` checkout. Code inspection establishes that implementation, not which process a user currently has running.

No database connection, model training, dependency installation, source modification or experiment registration was performed. PostgreSQL remains the operational source; workbooks are historical import/benchmark evidence. Existing database reconciliation reports were reviewed, not represented as fresh queries.

Supporting evidence:

- [Experiment inventory and methodology audit](research-experiment-audit.md): all seven registered runs, configuration, scores, runtimes and limitations.
- [Forecasting sources](research-forecast-sources.md) and [inventory-policy sources](research-inventory-sources.md): primary literature, implementation constraints and counterevidence.
- [Independent metric check](research-metric-check.json): recomputed directly from archived baseline predictions using summed absolute, signed and negative errors divided by summed actual sales.
- [Source fingerprints](research-source-hashes.json): SHA-256 of inspected application/calculator files and comparison table. All 73 available archived files listed by the seven run manifests matched their recorded hashes.

## What the experiments actually establish

The [registry](C:/Users/User/Desktop/hackathon/experiments/INDEX.md) groups seven runs under the same source/target signature and 65,754 forecast keys. Development origins are monthly July–December 2025; January–August 2026 is an already-known retrospective comparison. Targets are cumulative gross-positive outgoing recorded sales over 7/28 days, split by supplier and sales unit. No score measures latent unconstrained demand or purchase-order correctness.

The original experiment evaluated six rules and selected among four short-history rules, choosing capped weekly EWMA for all four 28-day groups. SBA/TSB did not consistently beat it. Tweedie LightGBM beat L2 in development, but its original version did not beat the selected baseline in any 28-day development group. Removing SKU identity generally hurt; removing calendar or weekly-lag features had group-specific effects. Document-level cleaning, cleaned-only features and combined raw/clean/bulk features did not establish a universal improvement. The combined experiment's development-selected final forecast retained the original baseline in every supplier/unit/horizon group.

The table below uses identical retrospective 28-day targets. Cells are **WAPE / bias / underforecast volume ratio**, all percent. Underforecast is `sum(max(actual−forecast,0))/sum(actual)`; it is neither frequency of misses nor stockout rate. Positive bias means overforecast. Lower WAPE is better; `100−WAPE` is not an accuracy percentage.

| Supplier / unit | Selected capped benchmark | Uncapped weekly EWMA | Original Tweedie |
|---|---:|---:|---:|
| IEK / meters | 64.977 / −22.722 / 43.849 | 70.070 / +0.485 / 34.793 | 58.803 / −10.908 / 34.856 |
| IEK / packs | 42.567 / −12.258 / 27.413 | 51.301 / +3.398 / 23.951 | 46.293 / −0.157 / 23.225 |
| IEK / pieces | 40.245 / −10.436 / 25.341 | 43.118 / +0.594 / 21.262 | 40.152 / −2.107 / 21.129 |
| Systeme / pieces | 42.760 / −25.285 / 34.023 | 43.094 / +1.274 / 20.910 | 42.430 / −2.192 / 22.311 |

Sources: independent archived-prediction check for both EWMA columns; [comparison.csv](C:/Users/User/Desktop/hackathon/experiments/comparison.csv) for Tweedie. Rounded ratios may differ by 0.001 when reconstructed from rounded WAPE and bias. Cohort counts respectively: 857, 547, 14,288 and 4,406 SKU/origin rows; these are repeated observations, not unique SKU counts.

**Supported:** Tweedie has promising retrospective absolute-error gains for meters; capping trades lower absolute error for more missed volume; simple methods remain strong. **Not supported:** a universal model winner, an untouched 2026 test, reliable cold-start performance, or demonstrated purchasing savings. Aggregate near-zero bias also permits large offsetting SKU errors. For example, IEK intermittent pieces at 28 days have baseline WAPE 119.418% and underforecast 71.237%; Tweedie lowers underforecast to 56.764% while worsening WAPE to 121.744%. Selection depends on the decision loss, not one leaderboard number.

## Application/research integration gap

The [actual engine](C:/Users/User/Desktop/hackathon-replenishment/backend/src/replenishment/calculation/engine.py) and [contracts](C:/Users/User/Desktop/hackathon-replenishment/backend/src/replenishment/calculation/contracts.py) implement `replenishment-ewma-v1`:

- Positive outgoing sales, exact supplier/SKU/warehouse/unit and pinned sheet/normalizer version; default 56-day history; missing transaction days become zero recorded sales.
- Daily weights `0.72 ** floor(age/7)`; manual document exclusions only, no automatic weekly cap or imported LightGBM predictor. Seasonality and growth multiply the rate as scenario assumptions.
- Forecast `rate × (lead time + review interval)` and buffer `rate × safety days`; subtract eligible free stock and dated inbound, clamp at zero, apply minimums and multiples. Daily shortage projection credits receipts before that day's demand and flags pre-arrival shortages.
- Unknown/negative available stock blocks the quantity. Cold/no-history items require review. Free stock is used once; otherwise one on-hand minus one reservation observation is required.

At **exactly 56 days**, factors 1, no exclusions, matching sales filters and full cohort eligibility, the application's weighted rate is algebraically the benchmark's **uncapped** weekly EWMA, apart from Decimal rounding. The selected benchmark instead caps each of eight weekly totals at twice the median positive weekly total. Equality holds only when no cap binds. Nondefault history lengths and manual assumptions break even the uncapped equivalence. The scores above therefore contextualize the formula; they are not an end-to-end application backtest.

The [UI](C:/Users/User/Desktop/hackathon-replenishment/frontend/src/Calculation.tsx) defaults to assumed L=14, R=7 and safety=7 days: a **21-day** forecast plus a seven-day-rate buffer, not the benchmark's 28-day forecast. Adding buffer does not change the forecast evaluation horizon. There is no empirically estimated lead-time distribution or calibrated service target.

Recent [source-default code](C:/Users/User/Desktop/hackathon-replenishment/backend/src/replenishment/calculation/reading.py) and [calculation documentation](C:/Users/User/Desktop/hackathon-replenishment/backend/CALCULATIONS.md) qualify older strict-mode descriptions: the UI starts with planning defaults enabled. It can infer unknown warehouse from the sole sales warehouse, infer eligible units from unique product observations, interpret imported rule kinds, assume a year for a yearless ETA, and use labelled monthly stock estimates. These are visible assumptions, not proof of operational correctness. A single sales warehouse does not establish the stock report's scope. Monthly estimates omit subsequent movements and reservations; the result's `estimate` flag must travel with any interpretation.

There is a **second calculator** under main checkout [planning/calculator.py](C:/Users/User/Desktop/hackathon/backend/src/replenishment/planning/calculator.py). It uses an arithmetic historical mean with optional cleaning and supplied stockout assumptions. The emerging [evaluation runner](C:/Users/User/Desktop/hackathon/backend/src/replenishment/evaluation/runner.py) imports this calculator, not the application worktree's EWMA engine. Its `backend_raw` name is not evidence of parity with the requested application. Reuse its metric/artifact machinery where appropriate, but evaluate the exact chosen callable and identify it by code hash. No completed output for that emerging runner was found in the inspected artifacts directory.

The application's API reads a repeatable-read, read-only PostgreSQL transaction. Its preview returns an exportable snapshot; it does not persist server-side runs. This is distinct from other purchasing work under development and from a certified supplier-order workflow.

## Evidence risks and data feasibility

| Issue | Finding and consequence | Addressable with present PostgreSQL evidence? |
|---|---|---|
| Temporal leakage | Reviewed feature windows precede origins; LightGBM training labels are fully observed by prediction origins (exclusive label end ≤ origin). The full-year workbook can nevertheless contain revisions unavailable historically. Current category/snapshot/seasonality values must not be backfilled into earlier origins. | Past-only filters/source hashes now; historical ingestion/availability timestamps require new records for strict as-was evaluation. |
| Repeated selection | Later cleaning, ablation and combined research already knew the 2026 scores. A 2025-only selector does not undo researcher adaptation. Six development and eight retrospective origins give limited time-block evidence; adjacent origins may be dependent. | Keep 2026 retrospective and preregister a future shadow test. |
| Cohort fairness | Registry matching supports identical gross targets, not equal features or all possible SKU coverage. Established-history eligibility omits cold starts; current application includes some recent-history items and blocks others. | Reconcile exact keys and publish separate new/short-history cohorts; do not pool them into the legacy result. |
| Missing/negative movements | Zeros between transactions are assumed no recorded sale, not known availability. Negative rows are not classified returns. Sparse 2023/24 movement dates do not provide full positive-sales history. | Inspect signed rows/document evidence; establish coverage and return/adjustment semantics with the owner. |
| Bulk demand | Large documents are observable; customer IDs and advance project commitments are absent. Capping may erase legitimate repeat demand. | Retain raw labels, expose candidate events and manager reasons. Customer concentration/known future demand needs new operational fields. |
| Stockout censoring | Monthly balances and one current snapshot cannot identify exact unavailable intervals or lost units. | No trustworthy latent-demand correction from present inputs alone. |
| Stock and reservations | IEK September stock is opening stock: 2,056 populated of 2,853 rows, not current free stock. Systeme has 497 on-hand/reserved/free rows, date from filename and uncertain scope. Receipts ledger is incomplete. | NULL/source reconciliation and explicit estimate mode now; authoritative dated balances, complete movements/reservation events require new feeds. |
| Units and receipts | Cable purchasing in coils vs sales in meters; no complete conversion table. Expected shipments are not order-to-actual-receipt lead-time history. | Surface known conflicts and date bases; obtain conversion, ETA/status, partial receipt and supplier-order history. |
| Costs and categories | `cost_unspecified` is not a confirmed purchase/sale cost or currency. Category codes lack a dictionary and as-of validity. | Preserve fields; do not invent costs, category hierarchy or economic optimum. |

Sources: [data audit](C:/Users/User/Desktop/hackathon/docs/DATA_AUDIT.md), [data model](C:/Users/User/Desktop/hackathon/docs/DATA_MODEL.md), [stock reconciliation](C:/Users/User/Desktop/hackathon-replenishment/docs/SUPPLIED_STOCK_FINDINGS.md), and the attached code/experiment audits. Full benchmark targets measure recorded sales. Evaluating an imputer against its own reconstructed demand would be circular.

## Ranked approaches: supporting and opposing evidence

1. **Exact baseline plus protection-period uncertainty.** Measure cumulative errors at L+R, then test a modest empirical residual buffer. MIT's [periodic-review material](https://ocw.mit.edu/courses/15-763j-manufacturing-system-and-supply-chain-design-spring-2005/e1800430fdccaf618b22bd551fc00fac_summary.pdf) supports this protection period. [Prak et al.](https://orca.cardiff.ac.uk/id/eprint/92130/) show why scaling one-step variance can understate lead-time error; their constant-level/constant-lead-time assumptions limit direct transfer. Our inference is to estimate horizon errors directly. Sparse tails and level changes can still defeat calibration.
2. **Reuse global LightGBM for direct cumulative quantiles.** [Official LightGBM](https://lightgbm.readthedocs.io/en/latest/Parameters.html) supports quantile loss; Tweedie alone does not produce calibrated quantiles. Global pooling is theoretically plausible ([Montero-Manso and Hyndman](https://arxiv.org/abs/2008.00444)), and existing feature infrastructure reduces effort. Against promotion: local development results were uneven, SKU dependence weakens unseen-item claims, and additional quantiles add calibration/crossing complexity. Keep a mean forecast separate from an upper purchasing quantile.
3. **Defer temporal aggregation and richer bootstrap until a residual failure justifies them.** ADIDA/IMAPA have [maintained implementations](https://nixtlaverse.nixtla.io/statsforecast/docs/models/adida.html) and offer a different time-scale assumption from SBA/TSB; fewer aggregates can delay level-shift response. [Willemain et al.](https://www.sciencedirect.com/science/article/pii/S016920700300013X) support intermittent-demand bootstrap on nine industrial datasets, but [Syntetos et al.](https://www.sciencedirect.com/science/article/pii/S0148296315001496) find simple methods competitive across over 7,000 series. This disagreement favors a simple distribution control, not a model tournament or deep-network replacement.

Bulk events belong in raw-demand uncertainty unless advance information or manager-confirmed exclusions exist. Annual seasonality and cold starts warrant cohort diagnostics, not unverified SKU multipliers. Ordinary conformal guarantees do not automatically hold under dependent, shifting demand; [adaptive conformal research](https://proceedings.neurips.cc/paper/2021/hash/0d441de75945e5acbc865406fc9a2559-Abstract.html) offers tools but not a guarantee of tight, per-SKU service bounds.

## Three concrete experiments

These are proposed acceptance thresholds, not measured gains or agreed business targets. Freeze them before running. All comparisons preserve supplier/unit/warehouse; no mixed-unit headline WAPE. Record wall time, peak memory, code/data hashes and prediction keys. Report WAPE, signed bias, under- and overforecast volume, MAE/MASE with undefined counts, monthly results, and regular/intermittent/bulk-heavy/new-item cuts. Define segments using information strictly before each origin. Preserve gross raw target quantities even when features are cleaned.

**Shared temporal protocol.** Replay the original July–December 2025 development and January–August 2026 retrospective origins; never describe newly chosen settings as independently validated by 2026. At each origin train/calibrate only on labels whose entire horizon has ended. Purge overlapping training/validation labels; preserve time blocks in uncertainty estimates rather than treating repeated SKU/origin rows as independent. Add H=21 for the current L14+R7 scenario; retain 7/28 only for registry comparability. If buyers specify another L/R, freeze that horizon before testing rather than interpolate a 28-day score.

For genuinely new evidence, freeze the protocol before **1 October 2026** and shadow forecasts on **1 October, 1 November and 1 December**, scoring only completed horizons. H=28 on December 1 completes December 28; evaluate after data completeness is confirmed. Earlier 2026 observations may be used for training, but future model selection cannot inspect shadow outcomes. Three origins are an initial gate, not proof of seasonal reliability. If no fresh feed arrives, results remain retrospective and promotion stays provisional.

### 1. Exact application baseline and target-alignment audit — first priority

**Hypothesis / segment:** naming and horizon differences obscure current quality; a fixed simple comparator establishes what is actually gained for every eligible supplier/unit, especially bulk-heavy items and recent-history SKUs.

**Data:** pinned PostgreSQL movements and source metadata already modeled/imported; export once under read-only transaction for reproducible offline evaluation. Confirm completeness through each target end. Inventory fields are unnecessary for isolated forecast scoring; use explicitly synthetic stock only if the callable requires it.

**Comparison:** call the actual `calculation.engine.calculate` with history=56, factors=1, no document exclusions and fixed H; compare (a) raw mean28, (b) archived uncapped weekly EWMA and (c) archived selected capped EWMA, or mean59 for its selected 7-day packs group. Assert forecast parity for (b) at matching configuration and eligibility within `H × 1e−12 + 1e−8` absolute rounding tolerance. Separately score actual configured factors/exclusions only when their as-of provenance exists.

**Splits/horizon/metrics:** shared protocol above; publish legacy common-cohort and additional application-eligible cohorts separately. No inventory simulation claim. Success is complete matched-key coverage, explained exclusions, parity and reproducible metrics. A simple candidate may advance only with at least 5% relative WAPE improvement and no more than 2 percentage points worse underforecast in its intended group, stable in at least two of three shadow origins. Reject parity failures or unexplained target/cohort differences before interpreting scores; retain the incumbent when no candidate qualifies. A loss tradeoff that fails this screen is evidence for experiment 2, not an automatic model swap.

**Effort / runtime / integration:** estimated 1–2 engineer-days using existing metric/artifact machinery plus a PostgreSQL source adapter. No training. Runtime must be measured; do not reuse LightGBM training timing as application latency. Reuse the exact public forecast callable rather than duplicate the formula. Keep Excel out of runtime calculations.

### 2. Calibrated horizon-residual buffer versus seven safety days

**Hypothesis / segment:** sparse and bulk-heavy items need an explicit uncertainty tradeoff; one rate-based safety buffer may give inconsistent protection across them.

**Data:** mature past forecast/actual pairs generated in experiment 1. No stockout correction. Use normalized signed residuals `(actual_H−forecast_H)/max(forecast_H,1 stock unit)`, pooled within supplier/unit and historical activity segment. Freeze the latest 12 completed calibration origins; where fewer than six origins exist in a segment, fall back to supplier/unit and mark low confidence. If that pool also lacks six origins, retain the current buffer and mark calibration not evaluable. Start at q=0.90 solely as a scenario, not a promised service level.

**Comparison:** same point forecast, same inputs and rounding; current `forecast_H + rate×7` versus `forecast_H + max(0, q90 residual × max(forecast_H,1))`. Do not add seven safety days again to the quantile target. Pooling is pragmatic, not individual-SKU calibration.

**Splits/horizon/metrics:** same frozen past-only protocol and exact H. Primary scores are one-sided pinball loss, target exceedance, sharpness/stock target and segment coverage; keep point bias/underforecast unchanged and report asymmetric buffer errors separately. Success: at least 5% lower pinball loss than the current buffered target, no intended group worse by more than 5%, and 85–95% aggregate coverage of the q90 target on the fresh period with segment counts and time-block uncertainty. Report strict and non-strict coverage for discrete ties; do not mislabel unavoidable zero-demand mass as calibration failure. Outside this range or unstable sparse segments means investigate, not promote; too few independent origins means inconclusive.

**Policy simulation:** paired observed-sales replay only, explicitly labelled hypothetical. Use the same synthetic starting free stock, zero starting backlog and known-empty pipeline; weekly reviews, deterministic L=14, arrivals before demand, seven-day-delay stress case, and separate lost-sales/backorder variants. Freeze any MOQ/conversions; skip unresolved rows. Measure immediate fill rate, stockout days, average/terminal inventory, terminal backlog, order frequency and rounding excess. Predeclare a 10% lower average inventory at fill rate within 1 percentage point as a provisional scenario gate; evaluate per item or transparently normalized within-unit groups. Report warm-up and terminal effects. Passing is scenario evidence only.

**Effort / runtime / integration:** estimated 2–4 engineer-days after experiment 1. Offline residual calculation is lightweight; serving is a lookup plus arithmetic. Twelve calibration origins give weak tail evidence: do not promise a per-SKU 90% service guarantee. Persist calibration version, pool and fallback provenance before integration.

### 3. Direct global quantile challenger — only after the controls work

**Hypothesis / segment:** pooled features can capture conditional uncertainty and changing sales levels better than a pooled residual buffer, particularly established regular items and selected intermittent cohorts.

**Data:** existing raw lag/rolling/calendar/SKU features from PostgreSQL exports, restricted to as-of observations. Do not add current category codes, future bulk labels, stock snapshots or invented customer IDs. New-item predictions use a documented fallback and are a separate result.

**Comparison:** fixed existing LightGBM structure and features with `objective=quantile` at 0.5 and 0.9, directly predicting H-total; compare q90 against experiment 2, q50 against an empirical median control, and retain the original Tweedie mean and exact application point forecast for mean/bias reporting. Fix one parameter configuration before replay; no broad tuning grid or repeat of failed combined features.

**Splits/horizon/metrics:** shared protocol, mature labels only; calibrate on earlier out-of-fold residuals. Report pinball at both levels, coverage, interval width, crossing frequency and runtime. If crossings are sorted, predeclare that operation and score the resulting forecasts. Advance only with at least 5% lower q90 pinball loss than experiment 2, coverage within the same band, no intended group >5% worse, and improvement in two of three fresh origins; otherwise reject or restrict the claim to a predeclared segment. Keep quantile optimism separate from mean bias. Repeat experiment 2's identical simulation before a policy claim.

**Effort / runtime / integration:** estimated 3–5 engineer-days; training cost scales with supplier/horizon/quantile fits and must be measured on the research environment. Reuse pinned research dependencies; do not install LightGBM into the backend until promotion. Integration requires versioned artifacts, feature parity, explicit nonnegative/crossing treatment, fallback and a deployment choice between offline predictions and serving. No runtime estimate here is a benchmark measurement.

## What must be collected before genuine inventory evaluation

Prioritize authoritative SKU/warehouse/unit free stock and reservations at the decision time; complete receipts/adjustments and partial shipment status; supplier order, promised and actual receipt dates; confirmed purchase-to-stock conversions and quantity rules; availability intervals or censoring indicators; customer requests/backorders/cancellations and optional anonymous customer/project identifiers. Define whether commitments are already reserved or forecast, to avoid double counting. Obtain holding/shortage cost semantics or agreed service priorities before monetary optimization.

Current sources cannot reconstruct counterfactual daily availability, complete inventory flows, historical ordering decisions or unconstrained demand. Thus a genuine historical inventory replay is not identifiable. A new forecast does not repair those missing inputs: [censored-newsvendor research](https://arxiv.org/abs/2412.01763) illustrates identification limits even with abundant censored observations. Cost ratios can be sensitivity assumptions, never reported as actual currency savings. With future operational telemetry, compare policies in shadow first and then measure realized outcomes under an agreed rollout.

## Team explanation

We have an explainable draft engine and useful sales benchmarks, not a validated automatic buyer. Typical aggregate 28-day errors remain substantial, with much worse sparse-item performance. The research winner and application are different formulas, and purchasing also depends on stock freshness, units and arrival timing. Keep the engine, first benchmark its exact PostgreSQL-backed path at the actual lead-time-plus-review horizon, then test a simple calibrated buffer before spending effort on another model.
