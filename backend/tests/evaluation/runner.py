"""Read-only sources, strict boundary, immutable standalone report runs."""

import argparse
import hashlib
import math
import platform
import resource
import statistics
import subprocess
import sys
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from evaluation.cases import ROOT, read_cases
from evaluation.contracts import VERSION, load_app, validate_requests, validate_results
from evaluation.report import render, scorecard, summarize, write_artifacts


def execute(cases, app):
    batch = [deepcopy(c["request"]) for c in cases if c["forecast_eligible"]]
    validate_requests(batch)
    reliability = {"contract_failures": 0, "invalid_outputs": 0, "calculation_errors": 0}
    performance = {
        "status": "N/A",
        "reason": "app_not_implemented" if app is None else "no_eligible_cases",
        "cold_seconds": None,
        "warm_median_seconds": None,
        "warm_p95_seconds": None,
        "sample_count": 0,
        "warmup_count": 0,
        "batch_size": len(batch),
        "platform": platform.platform(),
        "scope": "Calculation call only; copies/validation excluded",
    }
    results, failure = [], None

    def invoke():
        nonlocal failure
        payload = deepcopy(batch)
        start = time.perf_counter()
        try:
            output = app(payload)
        except Exception as exc:
            reliability["calculation_errors"] += 1
            failure = f"calculation_error:{type(exc).__name__}:{exc}"
            raise
        elapsed = time.perf_counter() - start
        try:
            validate_results(batch, output)
            if payload != batch:
                raise ValueError("Calculation mutated input")
        except Exception as exc:
            reliability["contract_failures"] += 1
            reliability["invalid_outputs"] += 1
            failure = f"contract_failure:{type(exc).__name__}:{exc}"
            raise
        return output, elapsed

    if app is not None and batch:
        try:
            results, cold = invoke()
            invoke()  # One explicit warm-up, excluded from the 20 measured warm samples.
            samples = [invoke()[1] for _ in range(20)]
            performance.update(
                status="measured",
                reason=None,
                cold_seconds=cold,
                warm_median_seconds=statistics.median(samples),
                warm_p95_seconds=sorted(samples)[math.ceil(0.95 * len(samples)) - 1],
                sample_count=20,
                warmup_count=1,
            )
        except Exception:
            if failure is None:
                raise
            performance.update(status="failed", reason=failure)
            results = []
    indexed = {r["case_id"]: r for r in results}
    for case in cases:
        case.update(
            forecast=None, result=None, status="skipped", skip_reasons=list(case["eligibility_reasons"])
        )
        if app is None:
            case["skip_reasons"].append("app_not_implemented")
        if not case["forecast_eligible"]:
            continue
        if failure:
            case["skip_reasons"].append(failure)
        elif case["case_id"] in indexed:
            result = indexed[case["case_id"]]
            case["result"] = deepcopy(result)
            if result["status"] == "ok":
                case.update(forecast=result["forecast"], status="evaluated")
            else:
                case["skip_reasons"].append(f"{result['status']}:{result['reason']}")
    rows_supplied = sum(len(item["history"]) for item in batch) if app is not None else 0
    return reliability, performance, rows_supplied


def provenance(command, sources):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    files = sorted((ROOT / "backend/tests/evaluation").glob("*.py")) + [
        ROOT / "scripts/evaluate.py",
        ROOT / "scripts/check_eval_contract.py",
        ROOT / "backend/uv.lock",
        ROOT / "backend/pyproject.toml",
        ROOT / "docs/INVENTORY_EVALUATION.md",
        ROOT / "backend/src/replenishment/intake/adapters/xlsx.py",
        ROOT / "backend/src/replenishment/intake/adapters/normalization.py",
    ]
    return {
        "protocol": VERSION,
        "year": 2024,
        "command": command,
        "working_directory": "backend",
        "sources": sources,
        "code_revision": git("rev-parse", "HEAD"),
        "dirty_state": git("status", "--porcelain"),
        "code_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        "environment": {"python": sys.version, "platform": platform.platform()},
        "selection": "Both pinned monthly sales workbooks; all SKUs; Jan→Feb through Nov→Dec. "
        "Unknown units excluded from forecast metrics; no cross-source unit/scope assumptions.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2024, choices=[2024])
    parser.add_argument("--require-app", action="store_true")
    parser.add_argument("--output", type=Path, help="New immutable directory; must not exist")
    args = parser.parse_args(argv)
    cpu = time.process_time()
    start = time.perf_counter()
    cases, sources, resources = read_cases(args.year)
    preparation = time.perf_counter() - start
    app = load_app()
    reliability, performance, rows_supplied = execute(cases, app)
    summary = summarize(cases, app is not None, reliability)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + VERSION
    summary["run_id"] = run_id
    memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    resources.update(
        rows_supplied=rows_supplied,
        cpu_seconds=time.process_time() - cpu,
        peak_process_memory_bytes=memory if sys.platform == "darwin" else memory * 1024,
        process_scope="Whole evaluation process high-water RSS and CPU through calculation; "
        "not app-only memory; excludes artifact rendering/writing",
    )
    summary["resources"] = resources
    summary["performance"] = {
        "app": performance,
        "harness": {
            "input_preparation_seconds": preparation,
            "report_generation_seconds": None,
            "report_generation_scope": "One in-memory HTML render; excludes writes/final serialization",
        },
    }
    start = time.perf_counter()
    render(summary, cases)
    summary["performance"]["harness"]["report_generation_seconds"] = time.perf_counter() - start
    output = args.output or ROOT / "artifacts/inventory-evaluation" / run_id
    manifest = provenance(
        [sys.executable, "../scripts/evaluate.py", *(argv if argv is not None else sys.argv[1:])], sources
    )
    manifest.update(run_id=run_id, created_at=datetime.now(UTC).isoformat())
    write_artifacts(output, manifest, summary, cases)
    for relative, expected in manifest["code_sha256"].items():
        content = (ROOT / relative).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"Code changed during run: {relative}")
        destination = output / "code" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    print("\n".join(scorecard(summary)))
    if summary["status"] == "FAIL":
        return 1
    if args.require_app:
        if app is None or summary["coverage"]["evaluated"] == 0:
            return 1
        return subprocess.call(
            [sys.executable, "-m", "pytest", "-q", "tests/evaluation/test_app.py", "--require-app"],
            cwd=ROOT / "backend",
        )
    return 0
