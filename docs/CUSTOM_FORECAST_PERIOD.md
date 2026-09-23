# Custom forecast period

The period picker accepts arbitrary start/end dates (inclusive), or a duration of
1–730 days. Changing either date recomputes the duration; entering a duration
changes the end date. There are no fixed forecast-period presets.

`PlanningRequest.forecast_end` is an optional inclusive end date. When supplied,
it overrides the lead-time-plus-review coverage horizon for every row. Lead time
still determines the arrival date and pre-arrival shortage. Receipts on the last
selected day are eligible; receipts after that day are outside coverage. The
response retains its existing exclusive `coverage_end` convention. Missing
`forecast_end` preserves the original per-row lead-plus-review behavior.

`forecast_method="auto"` selects uncapped weekly EWMA over the last 56 days of
the declared history, using weights `0.72 ** floor(age / 7)`. Short history or
enabled stockout compensation uses the existing history-mean policy. Explicit
per-row daily demand retains precedence. Results identify the actual method.
The default API value remains `history_mean` for existing callers. UI forecast
requests explicitly opt into auto. These are baseline policies; no LightGBM
model, calibrated safety buffer, or new accuracy claim is introduced.

Existing scenario JSON stores the additional input/result fields without a
database schema migration. Old saved scenarios remain readable. Real source
observations are unchanged. API processes must reload the updated Python code.
