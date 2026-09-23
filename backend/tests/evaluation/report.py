"""One scorecard feeds CLI, JSON and an offline Russian HTML report."""

import csv
import html
import json
from collections import Counter, defaultdict
from pathlib import Path

from evaluation.contracts import VERSION
from evaluation.metrics import forecast_metrics


def summarize(cases, app_present, reliability):
    groups = defaultdict(list)
    for case in cases:
        groups[(case["supplier"], case["unit"], None)].append(case)
        groups[(case["supplier"], case["unit"], case["target_month"])].append(case)
    quality = []
    for (supplier, unit, month), members in sorted(groups.items(), key=lambda pair: repr(pair[0])):
        pairs = [(c["actual"], c["forecast"]) for c in members if c["status"] == "evaluated"]
        metrics = forecast_metrics(pairs)
        metrics.update(
            supplier=supplier,
            unit=unit,
            month=month,
            candidate=len(members),
            evaluated=len(pairs),
            skipped=len(members) - len(pairs),
            status="evaluated" if pairs else "not_evaluated",
            percentage_status="evaluated"
            if pairs and metrics["wape_pct"] is not None
            else "undefined_zero_actual"
            if pairs
            else "not_evaluated",
        )
        metrics["denominators"] = {
            name: {
                "evaluated": len(pairs) if defined else 0,
                "skipped": len(members) - len(pairs) if defined else len(members),
                "value": metrics["actual_total"] if name in {"wape_pct", "bias_pct"} else len(pairs),
            }
            for name, defined in (
                ("wape_pct", metrics["wape_pct"] is not None),
                ("bias_pct", metrics["bias_pct"] is not None),
                ("mae", bool(pairs)),
                ("underforecast", bool(pairs)),
            )
        }
        quality.append(metrics)
    count = sum(c["status"] == "evaluated" for c in cases)
    reasons = Counter(reason for c in cases for reason in c["skip_reasons"])
    failed = any(reliability.values())
    return {
        "contract_version": VERSION,
        "status": "FAIL" if failed else "EVALUATED" if count else "NOT EVALUATED",
        "app_status": "available" if app_present else "app_not_implemented",
        "coverage": {
            "candidate": len(cases),
            "eligible": sum(c["forecast_eligible"] for c in cases),
            "evaluated": count,
            "skipped": len(cases) - count,
            "reasons": dict(sorted(reasons.items())),
        },
        "quality": quality,
        "inventory": {
            "status": "not_evaluated",
            "evaluated": 0,
            "skipped": len(cases),
            "mean_month_end_stock": None,
            "final_stock": None,
            "unmet_recorded_demand": None,
            "fulfilled_recorded_ratio": None,
            "reasons": ["stock_timing_scope_unconfirmed", "historical_receipts_missing"],
        },
        "reliability": reliability,
        "llm": {
            "status": "N/A",
            "reason": "No harness LLM calls; provider accounting unavailable for future app execution.",
        },
    }


def scorecard(summary):
    coverage = summary["coverage"]
    measured = [g for g in summary["quality"] if g["month"] is None and g["evaluated"]]
    quality = "; ".join(
        f"{g['supplier']}/{g['unit']}: WAPE={g['wape_pct'] or 'N/A'}%, "
        f"bias={g['bias_pct'] or 'N/A'}%, MAE={g['mae']}, "
        f"недопрогноз={g['underforecast']} ({g['evaluated']}/{g['candidate']})"
        for g in measured
    )
    resources = summary["resources"]
    perf = summary["performance"]
    app = perf["app"]
    latency = (
        f"cold={app['cold_seconds']:.4f}s; warm median={app['warm_median_seconds']:.4f}s; "
        f"p95={app['warm_p95_seconds']:.4f}s; n={app['sample_count']}"
        if app["status"] == "measured"
        else "N/A"
    )
    return [
        f"Запуск: {summary['run_id']} — {summary['status']} ({summary['app_status']})",
        f"Охват: кандидаты {coverage['candidate']}; допущены {coverage['eligible']}; "
        f"оценены {coverage['evaluated']}; пропущены {coverage['skipped']}",
        f"Качество: {quality or 'N/A — нет рассчитанных прогнозов'}",
        f"Запасы: N/A — нет подтверждённой истории поставок/остатков; пропущены {coverage['candidate']}",
        f"Производительность/ресурсы: app={latency}; "
        f"подготовка={perf['harness']['input_preparation_seconds']:.3f}s; "
        f"отчёт={perf['harness'].get('report_generation_seconds')}s; "
        f"источники={resources['source_bytes_opened']} bytes; строки={resources['rows_inspected']}; "
        f"передано={resources['rows_supplied']}; CPU={resources['cpu_seconds']:.3f}s; "
        f"пик процесса={resources['peak_process_memory_bytes']} bytes",
    ]


def render(summary, cases):
    escape = html.escape
    cards = "".join(f"<p>{escape(line)}</p>" for line in scorecard(summary))
    monthly = [g for g in summary["quality"] if g["month"] and g["evaluated"]]
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{escape(str(g[k]))}</td>"
            for k in ("supplier", "unit", "month", "evaluated", "skipped", "wape_pct", "bias_pct", "mae")
        )
        + "</tr>"
        for g in monthly
    )
    skipped = "".join(
        f"<tr><td>{escape(c['case_id'])}</td><td>{escape(c['supplier'])}</td>"
        f"<td>{escape(c['sku'])}</td><td>{escape(c['target_month'])}</td>"
        f"<td>{escape('; '.join(c['skip_reasons']))}</td></tr>"
        for c in cases
        if c["status"] != "evaluated"
    )
    payload = json.dumps(summary, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Оценка пополнения</title>
<style>body{{font:16px system-ui;max-width:1200px;margin:2rem auto;padding:0 1rem;color:#182532}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:.5rem;border:1px solid #ccd}}
td{{overflow-wrap:anywhere}}summary{{cursor:pointer}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}</style>
<h1>Готовность к оценке · 2024</h1>{cards}
<p>Продажи — наблюдения, не доказательство полного спроса. Ошибка прогноза не доказывает пользу для запасов.
Единицы в месячных продажах не указаны; складской охват неизвестен. Данные 2026 года не перенесены в 2024.
Механические примеры не включены в бизнес-метрики. Денежная экономия и улучшение: N/A.</p>
<h2>По месяцам</h2>{
        "<table><tr><th>Поставщик</th><th>Ед.</th><th>Месяц</th><th>Оценены</th>"
        "<th>Пропущены</th><th>WAPE %</th><th>Bias %</th><th>MAE</th></tr>" + rows + "</table>"
        if rows
        else "<p>N/A — нет рассчитанных прогнозов. Все кандидаты сохранены в cases.csv.</p>"
    }
<details><summary>Пропущенные случаи ({summary["coverage"]["skipped"]})</summary>
<table><tr><th>ID</th><th>Поставщик</th><th>SKU</th><th>Месяц</th><th>Причины</th></tr>{
        skipped
    }</table></details>
<details><summary>Метрики, знаменатели и область измерений</summary><pre>{
        escape(json.dumps(summary, ensure_ascii=False, indent=2))
    }</pre></details>
<script id="results" type="application/json">{payload}</script></html>"""


def write_artifacts(directory: Path, manifest, summary, cases):
    directory.mkdir(parents=True, exist_ok=False)
    for name, payload in (("manifest.json", manifest), ("results.json", summary)):
        (directory / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    columns = [
        "case_id",
        "supplier",
        "sku",
        "unit",
        "origin",
        "target_month",
        "actual",
        "forecast",
        "result",
        "status",
        "forecast_eligible",
        "inventory_eligible",
        "eligibility_reasons",
        "skip_reasons",
        "inventory_reasons",
        "sources",
    ]
    with (directory / "cases.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    k: json.dumps(case[k], ensure_ascii=False)
                    if isinstance(case[k], (list, dict))
                    else case[k]
                    for k in columns
                }
            )
    (directory / "report.html").write_text(render(summary, cases), encoding="utf-8")
