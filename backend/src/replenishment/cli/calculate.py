"""Calculate and persist supplier recommendations from pinned PostgreSQL observations."""

import argparse
import json
import os
from datetime import date
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine

from replenishment.calculation.inputs import SOURCE_TABLES, load_run_batch
from replenishment.calculation.llm import BudgetLedger, load_llm_client, run_historical_pilot
from replenishment.calculation.persistence import export_csv, json_value, run_calculation
from replenishment.cli.import_excel import NORMALIZER_VERSION
from replenishment.schema import metadata


def manifest_selection(manifest, version):
    """Pin every supplied workbook by hash and every observation by normalizer version."""
    entries = json.loads(Path(manifest).read_text(encoding="utf-8"))
    hashes = sorted({item["sha256"] for item in entries if item.get("path", "").endswith(".xlsx")})
    if not hashes:
        raise ValueError("The manifest contains no XLSX source hashes")
    return [
        {"table": table, "sha256": digest, "normalizer_version": version}
        for table in SOURCE_TABLES
        for digest in hashes
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--planning-date",
        type=date.fromisoformat,
        default=date(2026, 9, 22),
        help="Documented snapshot assumption: 2026-09-22",
    )
    parser.add_argument("--normalizer-version", default=NORMALIZER_VERSION)
    parser.add_argument(
        "--manifest", type=Path, default=Path(__file__).resolve().parents[4] / "docs/sources/manifest.json"
    )
    parser.add_argument("--sources", type=Path, help="Explicit JSON list of table/hash/version selections")
    parser.add_argument("--supplier", choices=("iek", "systeme"))
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument(
        "--llm-config", type=Path, help="Explicit LLM model/pricing config for diagnostic pilot"
    )
    parser.add_argument("--llm-cache", type=Path, help="Persistent exact-input cache for the LLM pilot")
    parser.add_argument("--llm-sample-size", type=int, default=3)
    parser.add_argument("--export", type=Path, help="Create a recommendation CSV; existing files are refused")
    parser.add_argument(
        "--export-run", type=UUID, help="Export an existing completed run without recalculating"
    )
    args = parser.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("DATABASE_URL is required; apply migrations and import source workbooks first")
    if args.export_run and not args.export:
        parser.error("--export-run requires --export")
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        if args.export_run:
            run = {"id": args.export_run, "reused": True}
        else:
            selection = (
                json.loads(args.sources.read_text(encoding="utf-8"))
                if args.sources
                else manifest_selection(args.manifest, args.normalizer_version)
            )
            batch = load_run_batch(
                engine, metadata, args.planning_date, selection, supplier=args.supplier
            )
            if args.llm_sample_size <= 0:
                raise ValueError("--llm-sample-size must be positive")
            llm = load_llm_client(
                args.llm_config,
                cache_path=args.llm_cache,
                budget=BudgetLedger(),
            )
            if llm is not None:
                pilot = run_historical_pilot(llm, batch, sample_size=args.llm_sample_size)
                batch["parameters"]["llm_pilot"] = pilot
                batch["llm_accounting"] = pilot["accounting"]
            else:
                batch["llm_accounting"] = {
                    "enabled": False,
                    "reason": "not_configured",
                    "limit_usd": "1.00",
                    "spent_usd": "0",
                    "events": [],
                }
            run = run_calculation(engine, batch, rerun=args.rerun)
        if args.export:
            with engine.connect() as connection:
                content = export_csv(connection, metadata, run["id"], args.supplier)
            with args.export.open("x", encoding="utf-8-sig", newline="") as output:
                output.write(content)
            run["export"] = str(args.export.resolve())
        print(json.dumps(json_value(run), ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
