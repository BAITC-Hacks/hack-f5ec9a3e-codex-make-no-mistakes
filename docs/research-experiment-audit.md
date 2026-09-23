# Local experiment audit

Read-only audit on 2026-09-23 of the latest evidence in `C:/Users/User/Desktop/hackathon`, including uncommitted registered experiments. No experiment was rerun, dependency installed, source changed, or database accessed. Paths below refer to that source checkout unless stated otherwise. This is an inventory and methodological audit, not a fresh validation result.

The evidence supports keeping the development-selected baseline as the benchmark and full-feature Tweedie as a challenger. It does not establish a universal replacement or an inventory-policy improvement. The combined experiment's frozen selector retains the baseline in all eight supplier/unit/horizon groups. This selector compares only baseline, raw Tweedie and combined Tweedie, not every candidate ever tried.

## Shared target and protocol

- Inputs: the two supplier transaction workbooks under `docs/data/IEK` and `docs/data/Systeme electric`; source hashes are preserved in each manifest. Of 248,915 movement rows, 238,402 positive outgoing lines enter the experiment. Missing/invalid quantities and ambiguous/negative movements are excluded; negatives are not assumed to be returns. Cleaning ledgers additionally retain two report footer rows lacking identity/date. Source counts and treatment: `docs/DEMAND_CLEANING_RESULTS.md:26`.
- Target: gross recorded positive outgoing quantities, January 1, 2025 through August 31, 2026, Almaty. It is not unconstrained demand, regular-demand ground truth, or net sales. Unobserved transaction dates are zero recorded sales, not proven available days with no demand.
- Grain: supplier/SKU/unit/origin/horizon. Four independently scored groups: IEK meters, packs and pieces; Systeme pieces. No cross-unit quantity aggregation.
- Origins: first of July–December 2025 (six development origins); first of January–August 2026 (eight retrospective origins). Separate 7- and 28-day sums beginning at origin. Seven-day results represent month-start weeks only. Windows within either horizon do not overlap; horizons overlap each other. Training labels for boosting overlap because origins are weekly.
- Eligibility: first observed positive sale at least 90 days before origin. Dormant products and zero targets remain. Cold-start products are excluded; sampled mature-sales coverage is 99.74% IEK pieces, 99.99% meters, 99.91% packs and 99.37% Systeme pieces. These are quantity coverage, not SKU coverage or latent-demand coverage (`docs/DEMAND_RESULTS.md:43`).
- Every registered demand run has 65,754 forecast keys and comparison signature `7cb7a0efc3014f3d2bdf6e77831cd1fc0b2298130b721552fb527c7e96287816`; target hash `f6f2f05aa28e537e6ae2db77a5fa7db759cf2c251094a4ce6b9be1efe30895a0`. There are 20,098 retrospective 28-day targets. Warehouse, cohort, raw target and raw sparse/regular labels are held fixed.
- Sparse/intermittent means positive sales in fewer than four of the previous eight weeks, determined before each origin. Model settings are selected by aggregate 2025 WAPE separately for supplier/unit/horizon, not separately for sparse and regular subsets. 2026 had already been inspected before the later experiments and is retrospective; repeated follow-ups are not independent confirmations.

Evidence: `docs/DEMAND_EXPERIMENT.md:19`, `docs/INTERMITTENT_EXPERIMENT.md:19`, `docs/LIGHTGBM_EXPERIMENT.md:20`, `experiments/INDEX.md:7` and all seven manifests.

## Registered experiment inventory

| Registered run | Candidate inputs and method | Selection and finding | Recorded total runtime |
|---|---|---|---:|
| `20260923T093731649804Z-baseline-v1` | 59-day mean, 28-day mean, eight-week EWMA, capped EWMA; prior-year 364-day rule and seasonal blend are diagnostic | Four short-history methods selected on 2025; all 28d groups choose capped EWMA; 7d packs chooses 59d mean, other 7d groups capped EWMA. Seasonal rules lose retrospectively | Not recorded |
| `20260923T093758721157Z-intermittent-v1` | Daily Croston-SBA alpha .05/.1/.2; TSB size alpha .05/.1/.2 × occurrence alpha .01/.05/.1/.2; constant daily rate times horizon | One setting per family/group/horizon. TSB slightly improves only 28d meters retrospectively; loses other three 28d and all four 7d groups. Lower underforecasting exchanges for more overforecasting | 59.96s |
| `20260923T093912139814Z-lightgbm-v1` | Separate pooled-SKU model per supplier/unit/horizon; 29 history/calendar/identity features; L2 vs Tweedie power 1.5 | Tweedie wins against L2 in all eight development groups, but baseline wins all eight development comparisons. Tweedie beats baseline in 7/8 retrospective comparisons | 218.61s |
| `20260923T095929639835Z-lightgbm-ablation-v1` | Same Tweedie/settings; full 29, no SKU 28, no calendar 25, no weekly lags 21 features | Development-selected ablations beat baseline in 3/8 development and 4/8 retrospective groups but worsen full Tweedie in 6/8 retrospective groups. No-SKU worsens all retrospective groups. IEK packs 7d/no-week-lags is a narrow lead | 223.61s |
| `20260923T101945737047Z-demand-cleaning-v1` | Fixed document MAD cleaning followed by six baseline rules; fixed old baseline choice and reselected four-rule choice | Both cleaned baseline policies lose all four 28d development/retrospective groups. Fixed-choice cleaning improves all 7d groups in both periods but increases underforecasting | 189.87s |
| `20260923T102653146360Z-lightgbm-cleaning-v1` | Fixed raw vs cleaned 29-feature Tweedie, unchanged raw training/scoring labels | 28d packs improve vs raw Tweedie but remain worse than original baseline. Tiny pieces development improvement does not carry into 2026 | 376.99s |
| `20260923T104442154821Z-lightgbm-combined-v1` | 59 features = 29 raw + 17 cleaned-history + 13 document bulk signals; fixed Tweedie | Combined improves raw in 3/8 development and 2/8 retrospective groups. Baseline wins all eight choices against raw and combined using 2025 only | 416.79s |

Runtime is one local execution, with different amounts of preprocessing, model candidates, artifact writing and caching. It is not deployment latency or a controlled speed comparison. Intermittent model state updates took 0.19s while workbook reading took 35.97s. Initial boosting fit/predict took 163.92s; ablation 174.87s; combined 119.0s. Recorded environment: Windows, Python 3.10.4, NumPy 1.23.5, openpyxl 3.1.2, LightGBM 4.6.0 where applicable, two boosting threads. Production Python 3.12 is separate. Baseline original environment/runtime/code hashes were not recorded; code was captured at registration. Later snapshots say recorded code hashes matched.

### Exact baseline and feature definitions

`scripts/backtest_demand.py:28` takes the previous 56 daily values, forms eight nonoverlapping seven-day sums, reverses to newest first, and weights them by `0.72**week`. Uncapped EWMA equals weighted weekly sum divided by total weights, divided by seven, times horizon. Robust EWMA caps each **weekly total** at twice the median of **positive weekly totals in those same eight weeks**, then applies the same weights. It does not cap individual invoices or daily values. The 59-day mean is exactly the last 59 calendar-day values divided by 59, times horizon.

For complete 56-day histories, daily weighting by `.72**(offset//7)` with normalized daily weights is algebraically equivalent to uncapped weekly EWMA. It is not generally equivalent to the capped benchmark. A production implementation needs explicit parity checks before inheriting the capped benchmark's results. Manager document exclusion and the statistical weekly cap are distinct policies.

The parent audit independently rescored archived 2026 28-day uncapped `weekly_ewma` predictions in `C:/Users/User/Desktop/hackathon-research/docs/research-metric-check.json`: WAPE meters 70.070, packs 51.301, pieces 43.118, Systeme 43.094; bias +0.485, +3.398, +0.594, +1.274%; underforecast 34.793, 23.951, 21.262, 20.910%. Thus the strongly negative bias belongs to the **capped** benchmark comparator. It must not be attributed to the uncapped application formula: against this uncapped comparator, Tweedie is not a universal bias or underforecast improvement. This arithmetic equivalence still needs production cohort, dates and data-normalization parity before becoming an application validation claim.

Prior-year demand is the corresponding 7/28 days 364 days earlier, falling back to EWMA until 364 days of global history. Seasonal blend needs 420 global days, mixes EWMA and prior-year demand 50/50, and scales the prior-year component by the recent-56/prior-year-56 ratio clipped to [.5, 2]. This limited result does not reject seasonality generally (`scripts/backtest_demand.py:43`).

Boosting's 29 features: categorical SKU; age and days since positive sale; month sin/cos, weekday, day of month; mean and positive-day fraction over 7/14/28/56/84 days; eight weekly lags; 56-day maximum, standard deviation, positive-sale size; recent/previous 28-day ratio. Each fit pools SKU observations within one supplier/unit/horizon and predicts the direct horizon sum. Training starts at history day 90, sampled every seven days plus benchmark month starts. Settings: 150 rounds, .05 learning rate, 15 leaves, 50 minimum rows/leaf, L2 regularization 1, max-bin 63, deterministic column-wise training and seed 20260923. No early stopping or large hyperparameter search (`docs/LIGHTGBM_EXPERIMENT.md:22`).

Document cleaning groups positive lines into exact supplier/SKU/unit/warehouse/date/document orders, retaining source rows. It uses previous 56 days excluding same-day peers, requires eight orders on four days, flags strictly above `max(4*median, median+6*MAD)`, replaces isolated flagged quantities with median, and retains repeated elevation on three distinct days within ±7 days using only evidence before the forecast origin. Recent decisions are revisable. Missing customer IDs prevent customer concentration identification; these are candidate bulk documents, not verified projects/errors. Combined features add cleaned means/weekly lags/maximum/std/positive size/ratio and bulk count, fraction, mean excluded quantity in 7/28/56/84-day windows plus capped recency (`docs/DEMAND_CLEANING.md:16`, `docs/COMBINED_FORECAST_EXPERIMENT.md:10`).

## Numerical comparison

All numbers below are percentages, and columns remain separate physical-unit groups. WAPE is sum absolute forecast error / sum actual. Bias is sum signed forecast error / sum actual. Underforecast ratio is sum positive(actual−forecast) / sum actual; it is not stockout rate. Overforecast ratio is analogous; aggregate near-zero bias can hide offsetting SKU errors. MAE is available in manifests/comparison.csv but cannot be pooled across units.

### 28-day WAPE: development → retrospective

| Model | IEK meters | IEK packs | IEK pieces | Systeme pieces |
|---|---:|---:|---:|---:|
| Selected baseline | 50.471 → 64.977 | 41.098 → 42.567 | 36.057 → 40.245 | 66.951 → 42.760 |
| Selected SBA | 52.580 → 69.748 | 43.021 → 49.783 | 49.183 → 74.565 | 77.047 → 43.426 |
| Selected TSB | 49.139 → 64.749 | 40.441 → 50.648 | 36.033 → 41.260 | 71.015 → 45.176 |
| L2 boosting | 60.140 → 62.084 | 52.374 → 56.034 | 54.597 → 42.316 | 88.222 → 43.621 |
| Raw/full Tweedie | 53.751 → 58.803 | 41.338 → 46.293 | 36.060 → 40.152 | 67.012 → 42.430 |
| Selected ablation | 53.704 → 60.265 | 40.387 → 46.584 | 35.834 → 41.226 | 67.012 → 42.430 |
| Cleaned fixed baseline | 56.813 → 68.396 | 43.510 → 44.218 | 38.329 → 42.192 | 67.788 → 44.585 |
| Cleaned reselected baseline | 54.288 → 70.179 | 41.181 → 47.117 | 37.332 → 41.312 | 67.788 → 44.585 |
| Clean-only Tweedie | 54.091 → 59.028 | 40.981 → 44.515 | 36.044 → 40.207 | 72.135 → 42.825 |
| Combined Tweedie | 53.348 → 61.766 | 43.248 → 47.871 | 36.422 → 40.054 | 73.181 → 43.067 |

Source: `experiments/INDEX.md` and per-run manifests, cross-referenced with `experiments/comparison.csv`. Raw/full controls are repeated in later runs but are not independent experiments.

### 28-day retrospective bias / underforecast

| Model | IEK meters | IEK packs | IEK pieces | Systeme pieces |
|---|---:|---:|---:|---:|
| Selected baseline | -22.722 / 43.849 | -12.258 / 27.413 | -10.436 / 25.341 | -25.285 / 34.023 |
| TSB | +0.122 / 32.314 | +6.649 / 21.999 | +2.021 / 19.620 | +1.837 / 21.670 |
| Raw Tweedie | -10.908 / 34.856 | -0.157 / 23.225 | -2.107 / 21.129 | -2.192 / 22.311 |

Tweedie and TSB reduce underforecast quantity in these 28-day groups but increase overforecast quantity. That is a cost/service trade-off, not demonstrated inventory improvement (`docs/INTERMITTENT_RESULTS.md:29`, `docs/LIGHTGBM_EXPERIMENT.md:63`). Cleaned fixed-baseline 28d bias worsens to -43.851%, -27.922%, -20.779%, -30.865%, respectively.

### Seven-day and stability evidence

- Raw Tweedie development → retrospective WAPE: meters 82.687 → 85.829, packs 52.854 → 68.716, pieces 61.458 → 71.399, Systeme 91.044 → 73.505. Baseline: 79.690 → 92.697, 51.879 → 81.969, 59.210 → 71.928, 84.782 → 73.715. Its retrospective wins do not reverse the development selection result (`docs/LIGHTGBM_EXPERIMENT.md:52`).
- IEK packs/no-week-lags 7d: development 51.634 vs baseline 51.879; retrospective 66.990 vs 81.969. Bias improves from +13.626 to -2.199%, but underforecast rises from 34.172 to 34.595%, and sparse WAPE remains 148.714%. Its 28d counterpart loses to baseline (`docs/LIGHTGBM_ABLATION.md:9`).
- Fixed-choice baseline cleaning improves all four 7d groups in both periods; retrospective gains .486–5.671 percentage points, but underforecast increases in every group. Packs underforecast increases 34.172 → 45.230% (`docs/DEMAND_CLEANING_RESULTS.md:10`).
- Raw Tweedie 28d monthly wins against baseline: meters 6/8, packs 3/8, pieces 5/8, Systeme 5/8. TSB: 5/8, 1/8, 2/8, 3/8. Combined vs raw: 1/8, 3/8, 5/8, 3/8. Combined's 0.098pp pieces gain hides slightly worse intermittent WAPE (+.015pp) and underforecast (+.065pp); meters worsen 2.963pp overall and 3.166pp underforecast (`docs/COMBINED_FORECAST_RESULTS.md:84`).
- Sparse 28d baseline WAPE: meters 112.888, packs 122.556, pieces 119.418, Systeme 101.275. Raw Tweedie: 111.773, 97.488, 121.744, 107.255. Large aggregate scores do not imply reliable slow-mover forecasts. Zero predictions give 100% WAPE when total target is nonzero; this is a metric diagnostic, not a purchasing prescription.
- SBA forecasts 286,650 pieces across eight 28d windows for IEK `130200305_` with zero observed actual, dominating the pieces overforecast failure. Do not remove that SKU after observing its errors or infer discontinuation without availability evidence (`docs/INTERMITTENT_RESULTS.md`, sparse-failure section).
- Eight monthly origins give weak precision. Baseline comparison's descriptive 5,000-block bootstrap intervals mostly cross zero; only packs vs 59d mean is positive throughout. Adjacent months may be dependent. No significance or prospective generalization is established (`docs/DEMAND_RESULTS.md:43`).

## Leakage, fairness and reproducibility audit

Code references below can be inspected in the immutable combined snapshot at `experiments/runs/20260923T104442154821Z-lightgbm-combined-v1/code/`. Its five research scripts exactly match the corresponding live scripts at audit time; the snapshot provides durable line references.

| Check | Evidence and conclusion |
|---|---|
| Future observations in baseline | `code/backtest_demand.py:180` obtains first positive date; eligibility compares it with origin−90; `:186` slices strictly before origin. Complete-series SKU enumeration does not make future-only products eligible. `:190` uses future values only as targets. No temporal leakage found in this path. |
| Development selection | `code/backtest_demand.py:208` filters 2025 before model selection. `code/backtest_lightgbm.py:299` filters development before candidate selection; `:309` compares baseline/raw/combined with baseline winning ties. No 2026 scores enter these selectors. |
| Boosting training labels | `code/backtest_lightgbm.py:255` forms horizon sums; `:256` records exclusive label ends; `:259` masks ends <= forecast origin before passing features/labels into a fresh Dataset at `:272`. Future labels held in memory do not enter the masked training set. |
| Boosting features | `code/backtest_lightgbm.py:237` passes only `:offset` histories; `:39` defines history-only features. No September seasonal/growth sheets, prices, customer IDs or future availability enter. Future SKU vocabulary is used for stable categorical identity, but future quantities/eligibility are not used as features. |
| Historical cleaning | `code/cleaning.py:74` excludes orders on/after as-of, `:93` excludes same-day peers from thresholds, `:100` inspects only ±7-day neighbors from the already cutoff-filtered group. `code/backtest_cleaning.py:86` reuses final decisions only for orders older than seven days and recomputes the tail. Completed ±7-day neighborhoods justify that cache; latest features recompute as of each example, rather than using final-cutoff cleaned exports. |
| Bulk features | `code/backtest_lightgbm.py:74` rejects current/future orders; `:214` creates cleaning/bulk blocks at each training or evaluation cutoff. `:221` compares cached and prefix-only results at first training and last evaluation cutoffs. This is useful boundary evidence, not an exhaustive proof for every possible future data pattern. |
| Target/metric fairness | `scripts/register_experiment.py:28` rejects invalid actuals, differing actuals for identical keys, duplicate/nonfinite/negative predictions and incomplete cohorts. `:64` reconciles WAPE/bias/underforecast and `:68` MAE; `:74` hashes exact canonical targets. It verifies full-cohort metrics, not all subgroup/monthly metrics or feature leakage. |
| Cohort fairness | Raw targets, raw sparse/regular labels and identical keys are retained when cleaning. The retrospective clean-row sensitivity subset uses issues across all experiment dates and is explicitly a diagnostic, not a deployable filter (`docs/DEMAND_EXPERIMENT.md:47`). |
| Control parity | Later documents report exact full control reproduction for all 65,754 keys; immutable code and archived prediction files are preserved. This audit independently checked archive hashes and stored label cutoffs, not rerun model predictions. |

Independent read-only checks performed for this audit: recomputed SHA-256 of every present manifest-listed archived file in all seven runs (no mismatches); read all stored training.csv.gz records (224 initial boosting, 448 ablation, 224 clean boosting, 224 combined; zero label ends after origins); confirmed live and combined-snapshot research script hashes match. Manifests report verified full-cohort metric-group counts 16, 32, 32, 80, 48, 48, 80 in the run order above. Original baseline provenance remains limited despite intact registration hashes. Large prediction archives are locally present but Git-ignored, so a clean worktree or clone does not by itself reproduce the evidence.

Remaining methodological limits are consequential: repeated adaptive exploration of the same 2026 period, tiny development differences without stability gates, growing training volume between periods, overlapping training labels, coarse month-start evaluation, mature-SKU exclusion, unknown availability, and volume-weighted WAPE masking slow movers. Equal-target registry checks do not resolve those issues. No historical inventory simulation was performed, and the forecast benchmark's arithmetic/synthetic examples cannot establish fill rate, inventory reduction, profit or optimal replenishment.

The next comparison should preserve this legacy benchmark for regression, predeclare a new chronological selection/evaluation procedure, include an exact production-forecast comparator, use supplier/unit/horizon/segment and monthly stability gates, and measure shortage/excess trade-offs under explicitly agreed assumptions. Keep raw, cleaned and excluded quantities visible; do not silently promote statistical bulk flags to confirmed demand exclusions.
