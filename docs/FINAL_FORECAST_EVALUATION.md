# Final forecast / leftovers evaluation — 2026-09-23

**Verdict: forecast evaluation passes; leftover reduction remains unproven.**
Keep `recent_level` (mean of three latest valid observations). Current evidence
supports forecast-assisted planning, not a quantified inventory-saving claim.

Fresh evaluation of the current working tree used 3,017 IEK/Systeme series,
planning date 2026-09-22, and four hash-verified sales/stock workbooks from the
[source manifest](sources/manifest.json). Training and preprocessing use only
history before each origin; selection uses June–September 2025 origins and is
frozen before the January–May 2026 retrospective comparison. The latter is
previously examined data, not an unseen test set.

| Candidate | Development error | Retrospective error |
| --- | ---: | ---: |
| Recent level — retained | 0.856049 | 0.727624 |
| EWMA | 0.841429 | 0.709433 |
| Adjusted recent level | 0.848519 | 0.723248 |
| Adjusted EWMA | 0.834872 | 0.705226 |
| Seasonal damped | 1.037364 | 0.914029 |
| Adjusted seasonal damped | 1.026349 | 0.905120 |

Lower is better. Error is absolute forecast error normalized by each series'
mean training sales, balanced across products, horizons and suppliers—not a
percentage of inventory saved. Best development improvement is **2.47%**, below
the **3%** promotion gate. Forecast errors remain substantial: retained-model
retrospective error is 0.728 times the training-sales scale. Its normalized
underforecast is 0.422; this is neither a stockout rate nor measured lost sales.

Scored targets: **17,539 / 32,691 (53.65%)** development and
**20,321 / 43,686 (46.52%)** retrospective. Missing actuals account for the
remaining ledger targets. Another 1,171 / 523 series-origin cases lack training
history and are outside those denominators. Missing observations remain unknown,
not zero. Unknown units prevent pooled physical WAPE.

**Leftovers check:** January–April and May–August 2026 produce **0 eligible,
6,034 excluded product-period cases**. Every case lacks verified compatible
units, common stock/sales scope, available-stock basis, historical purchasing
policy and orders/deliveries, and supported recommendation arrival timing.
Fourteen cases lack a unique stock match; 1,108 Systeme cases also lack verified
balance timing. The current checker assesses evidence coverage; it does not
simulate purchasing. Neither leftover reduction nor unmet sales is measured.

**Next decision:** retain the baseline. To establish savings, collect the missing
inputs and replay company versus recommended replenishment per compatible
product, with the same recorded sales and dated arrivals. Report ending stock
and unmet recorded sales together; fewer leftovers with unmet sales cannot count
as improvement. Monthly balances alone cannot establish lost demand.

Verification performed:

```sh
backend/.venv/bin/python scripts/evaluate.py --output /tmp/final-forecast-leftovers-20260923.json
backend/.venv/bin/python scripts/check_eval_contract.py
cd backend
.venv/bin/python -m pytest -q tests/evaluation/test_leftovers.py tests/evaluation/test_evaluation.py
```

Fresh evaluation completed; contract check passed; **22 tests passed**. Output
path must be unused on rerun. This check covers six deterministic candidates;
LightGBM and paid LLM trials were not rerun. See the
[methodology and earlier research results](INVENTORY_EVALUATION.md).
