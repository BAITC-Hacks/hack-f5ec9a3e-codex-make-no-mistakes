"""Exercise the real imported SKU over HTTP; save only a labelled verification scenario.

Run against the isolated Docker verification installation:
python scripts/verify_purchasing_http.py --base-url http://127.0.0.1:8081
No source edits or supplier messages. The final revision is left unapproved.
"""

import argparse
import csv
import io
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/") + "/api/v1"

    def request(path, payload=None, method=None, expected=200, raw=False):
        data = None if payload is None else json.dumps(payload).encode()
        req = Request(base + path, data=data, method=method,
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=120) as response:
                status, content = response.status, response.read()
        except HTTPError as error:
            status, content = error.code, error.read()
        assert status == expected, (path, status, content.decode())
        return content.decode("utf-8-sig") if raw else json.loads(content)

    assert request("/health")["status"] == "ok"
    products = request("/tables/catalog?" + urlencode({"q": "300200745_"}))["items"]
    assert len(products) == 1, "Expected the audited Systeme SKU in imported data"
    prepared = request("/planning/source-input", {
        "product_ids": [products[0]["id"]], "planning_date": "2026-09-23",
        "warehouse": "Алматы", "normalizer_version": "v1",
    })
    scenario_input = prepared["input"]
    blocked = request("/planning/calculate", scenario_input)
    assert blocked["rows"][0]["status"] == "needs_input"
    row = scenario_input["rows"][0]
    assert row["sales"] and row["sources"], "Must retain imported sales and provenance"
    row.update({
        "stock_as_of": "2026-09-23", "stock_scope_confirmed": True,
        "purchase_unit": row["stock_unit"], "stock_per_purchase_unit": "1",
        "minimum_order": "0", "order_multiple": "6", "lead_time_days": 7,
        "incoming_complete": True, "constraints_confirmed": True, "basis": "assumed",
    })
    reason = "HTTP verification only: assume stock scope/date, 1:1 units, MOQ 0, multiple 6, lead 7 days."
    row["notes"].append(reason + " Assume listed arrivals on 2026-09-25. Not confirmed by EKT.")
    for incoming in row["incoming"]:
        incoming.update({"expected_on": "2026-09-25", "warehouse": row["warehouse"],
                         "stock_unit": row["stock_unit"]})
    calculated = request("/planning/calculate", scenario_input)
    assert calculated["rows"][0]["status"] == "scenario_only", calculated
    saved = request("/scenarios", {
        "name": "HTTP VERIFICATION ONLY - NOT A REAL ORDER - 300200745_", "input": scenario_input,
    }, expected=201)
    path = "/scenarios/" + saved["id"]
    assert saved["result"] == calculated
    request(path + "/export?expected_revision=1", expected=409)
    override = {"row_id": row["row_id"], "quantity": "6", "reason": "Verification only; do not buy."}
    revised = request(path, {"name": saved["name"], "input": scenario_input,
                            "expected_revision": 1, "overrides": [override]}, method="PUT")
    assert revised["revision"] == 2 and revised["approved_revision"] is None
    approval = {"expected_revision": 2, "approved_by": "Automated verification only",
                "acknowledge_scenario": True}
    request(path + "/approve", approval)
    exported = request(path + "/export?expected_revision=2", raw=True)
    exported_row = list(csv.DictReader(io.StringIO(exported)))[0]
    assert exported_row["approved_quantity"] == "6"
    assert exported_row["recommended_quantity"] == calculated["rows"][0]["recommended_quantity"]
    assert request(path)["approved_revision"] == 2
    invalidated = request(path, {"name": saved["name"], "input": scenario_input,
                                "expected_revision": 2, "overrides": []}, method="PUT")
    assert invalidated["revision"] == 3 and invalidated["approved_revision"] is None
    request(path + "/approve", approval, expected=409)
    request(path + "/export?expected_revision=3", expected=409)
    print(json.dumps({"status": "passed", "scenario_id": saved["id"], "final_revision": 3,
                      "final_approved_revision": None, "sales_documents": len(row["sales"]),
                      "source_references": len(row["sources"]),
                      "recommended_quantity": exported_row["recommended_quantity"],
                      "exported_approved_quantity": exported_row["approved_quantity"]}))


if __name__ == "__main__":
    main()
