"""Read-only synthetic calculator walkthrough; no database or source-file access."""

import argparse
import json
import sys
from itertools import groupby

from replenishment.planning.calculator import calculate
from replenishment.planning.demo import demo_cases
from replenishment.planning.models import PlanningRequest


def main(argv: list[str] | None = None) -> None:
    # Windows redirected stdout may default to cp1251, which cannot encode the
    # calculator's arithmetic symbols. Keep both report formats explicitly UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Synthetic purchasing calculation / Синтетический расчёт заказа"
    )
    parser.add_argument("--case", help="Run one case ID; omit to run every case / ID сценария")
    parser.add_argument("--json", action="store_true", help="Print validated inputs and results as JSON")
    args = parser.parse_args(argv)
    cases = demo_cases()
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            parser.error(f"Unknown case / Неизвестный сценарий: {args.case}")
    reports = []
    for case in cases:
        request = PlanningRequest.model_validate(case["input"])
        reports.append({
            "id": case["id"],
            "name": case["name"],
            "description": case["description"],
            "synthetic": True,
            "input": request.model_dump(mode="json"),
            "result": calculate(request).model_dump(mode="json"),
        })
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return
    print("SYNTHETIC DEMO / СИНТЕТИЧЕСКАЯ ДЕМОНСТРАЦИЯ — no orders sent / без отправки заказов")
    print("Calendar days; arrivals before demand; unmet demand carried forward.")
    print("Календарные дни; приход до расхода; неудовлетворённый спрос переносится.\n")
    for report in reports:
        print(f"[{report['id']}] {report['name']}\n{report['description']}")
        rows = sorted(report["result"]["rows"], key=lambda row: row["supplier"])
        for supplier, group in groupby(rows, key=lambda row: row["supplier"]):
            print(f"  Supplier / Поставщик: {supplier}")
            for row in group:
                quantity = row["recommended_quantity"]
                recommendation = "NEEDS INPUT / НУЖНЫ ДАННЫЕ" if quantity is None else str(quantity)
                print(f"    {row['sku']}: {recommendation} {row['purchase_unit'] or ''} [{row['status']}]")
                print(f"      {row['explanation']}")
                print(
                    "      Demand / Спрос: "
                    f"{row['forecast_demand']}; incoming / транзит: {row['eligible_incoming']}; "
                    f"buffer / буфер: {row['buffer']}"
                )
                if row["first_shortage_date"]:
                    print(
                        f"      Shortage / Дефицит: {row['first_shortage_date']}; "
                        f"pre-arrival / до прихода: {row['maximum_prearrival_shortfall']} {row['stock_unit']}"
                    )
                for note in row["missing_inputs"] + row["warnings"] + row["demand_adjustments"]:
                    print(f"      - {note}")
        for warning in report["result"]["warnings"]:
            print(f"  Warning / Предупреждение: {warning}")
        print()


if __name__ == "__main__":
    main()
