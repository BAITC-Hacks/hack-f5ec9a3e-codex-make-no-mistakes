# Routing experiments

These small routing snapshots are separate from the forecasting experiment registry.
They combine sourced geography with explicitly hypothetical delivery inputs.

| Run | Scope | Outcome |
| --- | --- | --- |
| [20260923T111348Z-almaty-road-v1](20260923T111348Z-almaty-road-v1/manifest.json) | Nine real Almaty delivery candidates, example depot, captured OSRM car matrix; synthetic orders and fleet | DisTEL Monday → Thursday; 74.614 → 66.431 km; stock/capacity counterexamples prevent the move |

Read [the analysis and reproduction instructions](../../docs/ALMATY_ROUTING_RESULTS.md).
Each run directory is immutable and includes source data, raw provider responses,
scenario inputs, results, route geometry, code snapshots, versions and file hashes.
Create another run directory for new experiments; do not rewrite existing results.
