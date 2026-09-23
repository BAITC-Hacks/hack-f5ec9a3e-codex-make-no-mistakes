import csv
import hashlib
import json
import re
from copy import deepcopy
from decimal import Decimal

import pytest

from evaluation.cases import ROOT, assemble, read_cases
from evaluation.checks import check, example, response
from evaluation.contracts import load_app, quantity, validate_requests, validate_results
from evaluation.metrics import replay
from evaluation.report import scorecard, summarize, write_artifacts
from evaluation.runner import execute


def test_tiny_checks():
    check()


def records():
    source = example()["history"][0]["sources"][0]
    return [
        {
            "supplier": "example",
            "sku": "0001_",
            "unit": "шт",
            "month": f"2024-{m:02}",
            "quantity": q,
            "source": source,
        }
        for m, q in ((1, Decimal(10)), (2, Decimal(0)), (3, None), (4, Decimal(-2)), (5, Decimal(4)))
    ]


def test_cases_preserve_zero_missing_conflict_and_no_target_leakage():
    cases = assemble(records(), 2024)
    assert len(cases) == 11
    first = next(c for c in cases if c["target_month"] == "2024-02")
    assert first["forecast_eligible"] and first["actual"] == "0"
    assert len(first["request"]["history"]) == 1
    validate_requests([first["request"]])
    assert all(h["month"] < first["target_month"] for h in first["request"]["history"])
    assert "actual" not in first["request"]
    assert any("blank_observation" in r for c in cases for r in c["eligibility_reasons"])
    assert any("negative_observation" in r for c in cases for r in c["eligibility_reasons"])
    assert any("missing_observation" in r for c in cases for r in c["eligibility_reasons"])
    changed = records() + [{**records()[1], "quantity": Decimal(20)}]
    conflict = next(c for c in assemble(changed, 2024) if c["target_month"] == "2024-02")
    assert "conflicting_observation:2024-02" in conflict["eligibility_reasons"]
    unknown = [{**r, "unit": None} for r in records()]
    assert all(not c["forecast_eligible"] for c in assemble(unknown, 2024))
    decimal_zero = records()
    decimal_zero[0]["quantity"] = Decimal("0E-12")
    decimal_zero[1]["quantity"] = Decimal("0E-12")
    zero_case = next(c for c in assemble(decimal_zero, 2024) if c["target_month"] == "2024-02")
    validate_requests([zero_case["request"]])
    assert quantity(zero_case["actual"]) == 0


def test_receipts_carry_forward_and_missing_continuity_ends_sequence():
    periods = [
        {"month": "2024-02", "demand": "2"},
        {"month": "2024-03", "demand": "8"},
        {"month": "2024-04", "demand": None},
        {"month": "2024-05", "demand": "99"},
    ]
    receipts = [
        {"id": "r", "month": "2024-03", "quantity": "4"},
        {"id": "pending", "month": "2024-05", "quantity": "7"},
    ]
    result = replay("10", periods, receipts)
    assert result["evaluated"] == 2 and result["skipped"] == 2
    assert result["final_stock"] == "4"  # 10 + 4 - 2 - 8; no reset to the original 10.
    assert result["pending_receipts"] == ["pending"]


def test_contract_rejects_nested_fields_order_without_stock_and_duplicates():
    request = example()
    bad = deepcopy(request)
    bad["history"][0]["actual"] = "12"
    with pytest.raises(ValueError):
        validate_requests([bad])
    with pytest.raises(ValueError):
        validate_requests([request, request])
    with pytest.raises(ValueError):
        validate_results([request], [{**response(request), "recommended_quantity": "10"}])


def test_app_import_errors_are_not_absence(monkeypatch):
    def broken(name):
        raise ModuleNotFoundError("Missing internal dependency", name="missing_dependency")

    monkeypatch.setattr("evaluation.contracts.importlib.import_module", broken)
    with pytest.raises(ModuleNotFoundError):
        load_app()


def test_execution_benchmark_and_failure_classification():
    cases = assemble(records(), 2024)
    calls = []

    def app(batch):
        calls.append(deepcopy(batch))
        return [response(r, "0") for r in batch]

    reliability, timing, rows = execute(cases, app)
    assert len(calls) == 22 and all(batch == calls[0] for batch in calls)
    assert timing["sample_count"] == 20 and timing["warmup_count"] == 1
    assert rows == 1 and not any(reliability.values())
    summary = summarize(cases, True, reliability)
    assert summary["coverage"]["evaluated"] == 1
    assert summary["quality"][0]["percentage_status"] == "undefined_zero_actual"
    assert summarize(cases, True, execute(cases, lambda batch: [])[0])["status"] == "FAIL"

    def broken(batch):
        raise RuntimeError("broken app")

    assert execute(cases, broken)[0]["calculation_errors"] == 1


@pytest.fixture(scope="module")
def real_data():
    return read_cases()


def test_real_selection_deterministic_sources_unchanged_and_units_not_invented(real_data):
    cases, sources, resources = real_data
    repeated, _, _ = read_cases()
    assert cases == repeated
    assert {c["supplier"] for c in cases} == {"iek", "systeme"}
    assert len(cases) == len({(c["supplier"], c["sku"]) for c in cases}) * 11
    assert len({c["case_id"] for c in cases}) == len(cases)
    assert all(c["unit"] is None and "unknown_unit" in c["eligibility_reasons"] for c in cases)
    assert all(quantity(c["actual"]) >= 0 for c in cases if c["actual"] is not None)
    assert resources["rows_inspected"] > 3000
    assert resources["excluded_sheets"]
    for source in sources:
        assert hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest() == source["sha256"]


def test_json_csv_html_cli_agree_and_run_is_immutable(tmp_path, real_data):
    cases = deepcopy(real_data[0])
    reliability, perf, rows = execute(cases, None)
    summary = summarize(cases, False, reliability)
    summary.update(
        run_id="test",
        resources={**real_data[2], "rows_supplied": rows, "cpu_seconds": 0, "peak_process_memory_bytes": 0},
        performance={"app": perf, "harness": {"input_preparation_seconds": 0}},
    )
    output = tmp_path / "run"
    write_artifacts(output, {"protocol": summary["contract_version"]}, summary, cases)
    result = json.loads((output / "results.json").read_text())
    with (output / "cases.csv").open() as stream:
        ledger = list(csv.DictReader(stream))
    report = (output / "report.html").read_text()
    embedded = json.loads(
        re.search(r'<script id="results" type="application/json">(.*?)</script>', report)[1]
    )
    assert embedded == result == summary
    assert len(ledger) == result["coverage"]["candidate"]
    assert sum(r["status"] == "skipped" for r in ledger) == result["coverage"]["skipped"]
    assert {r["case_id"] for r in ledger} == {c["case_id"] for c in cases}
    assert all(json.loads(row["skip_reasons"]) for row in ledger)
    assert summary["status"] == "NOT EVALUATED" and len(scorecard(summary)) == 5
    assert "src=" not in report and "href=" not in report
    with pytest.raises(FileExistsError):
        write_artifacts(output, {}, summary, cases)


def test_source_corruption_fails(tmp_path, real_data):
    sources = real_data[1]
    manifest = tmp_path / "docs/sources/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(sources))
    for source in sources:
        path = tmp_path / source["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash/size mismatch"):
        read_cases(root=tmp_path)


@pytest.mark.parametrize("present", [False, True])
def test_strict_cli_fails_without_executed_real_cases(tmp_path, monkeypatch, capsys, present):
    from evaluation import runner

    def unavailable(batch):
        return [
            {**response(r), "status": "unsupported", "forecast": None, "reason": "not_supported"}
            for r in batch
        ]

    monkeypatch.setattr(runner, "load_app", lambda: unavailable if present else None)
    monkeypatch.setattr(
        runner,
        "read_cases",
        lambda year: (
            assemble(records(), year),
            [],
            {
                "source_bytes_opened": 0,
                "rows_inspected": 0,
            },
        ),
    )
    monkeypatch.setattr(runner, "provenance", lambda command, sources: {"code_sha256": {}})
    output = tmp_path / "strict"
    assert runner.main(["--require-app", "--output", str(output)]) == 1
    assert len(capsys.readouterr().out.splitlines()) == 5
    assert json.loads((output / "results.json").read_text())["status"] == "NOT EVALUATED"
