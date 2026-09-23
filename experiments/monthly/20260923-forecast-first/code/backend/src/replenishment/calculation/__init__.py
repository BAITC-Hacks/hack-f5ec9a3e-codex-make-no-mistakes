"""Pure forecast and purchasing calculation boundary."""

from __future__ import annotations

from .contracts import CONTRACT_VERSION, planning_date, validate_batch, validate_results
from .evaluation import evaluate
from .forecasting import _add_months, forecast_batch
from .purchasing import build_drafts


def calculate(batch: dict) -> dict:
    """Select on completed development targets, then forecast and build drafts."""
    validate_batch(batch)
    planning = planning_date(batch["planning_date"])
    cutoff = planning.replace(day=1)
    development = [
        f"2025-{m:02}-01" for m in range(6, 10) if _add_months(planning_date(f"2025-{m:02}-01"), 3) < cutoff
    ]
    retrospective = [
        f"2026-{m:02}-01" for m in range(1, 6) if _add_months(planning_date(f"2026-{m:02}-01"), 3) < cutoff
    ]
    evaluation = evaluate(batch["series"], development, retrospective)
    model = evaluation["selection_frozen"] or "recent_level"
    forecasts, bridges = forecast_batch(
        batch["series"], batch["planning_date"], include_bridge=True, model=model
    )
    drafts = build_drafts(batch, forecasts, bridges)
    # Persist bounded summaries; full target ledgers belong in evaluation exports.
    for phase in ("development", "retrospective"):
        detail = evaluation[phase]
        if detail is not None:
            detail.pop("rows")
            excluded = detail.pop("excluded")
            detail["excluded_count"] = len(excluded)
            detail["excluded_examples"] = excluded[:20]
    by_series = {}
    for row in forecasts:
        by_series.setdefault(row["series_id"], []).append(row)
    quality = {
        "series_count": len(batch["series"]),
        "forecast_count": len(forecasts),
        "insufficient_series": sorted(
            series_id
            for series_id, rows in by_series.items()
            if not any(row["status"] == "ok" for row in rows)
        ),
        "anomalies": {
            series_id: sorted({stamp for row in rows for stamp in row["explanation"].get("anomalies", [])})
            for series_id, rows in by_series.items()
            if any(row["explanation"].get("anomalies") for row in rows)
        },
        "parameters": {"ewma_alpha": "0.3", "trend_damping": "0.8", "target_month_count": 3},
        "source_selection": batch["source_selection"],
        "evaluation": evaluation,
    }
    result = {
        "contract_version": CONTRACT_VERSION,
        "planning_date": batch["planning_date"],
        "target_months": [_add_months(planning, offset).isoformat() for offset in (1, 2, 3)],
        "forecasts": forecasts,
        "drafts": drafts,
        "quality": quality,
    }
    if "llm_accounting" in batch:
        result["llm_accounting"] = batch["llm_accounting"]
    return validate_results(batch, result)


__all__ = ["calculate", "CONTRACT_VERSION", "validate_batch", "validate_results"]
