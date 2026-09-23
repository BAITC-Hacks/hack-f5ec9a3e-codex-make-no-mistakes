"""The result contract is stored atomically and exported without changing quantities."""

import csv
import io
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, select

from replenishment.schema import metadata


def test_calculation_tables_have_typed_result_columns():
    names = {"calculation_runs", "calculation_inputs", "calculation_forecasts", "calculation_drafts"}
    assert names <= metadata.tables.keys()
    assert str(metadata.tables["calculation_forecasts"].c.quantity.type) == "NUMERIC(30, 12)"
    assert str(metadata.tables["calculation_drafts"].c.coverage_start.type) == "DATE"


def test_cli_pins_original_workbook_hashes_and_every_normalizer_version():
    from replenishment.cli.calculate import SOURCE_TABLES, manifest_selection

    root = Path(__file__).resolve().parents[2]
    selected = manifest_selection(root / "docs/sources/manifest.json", "v2")
    assert len({row["sha256"] for row in selected}) == 12
    assert {row["table"] for row in selected} == set(SOURCE_TABLES)
    assert all(row["normalizer_version"] == "v2" for row in selected)


@pytest.fixture(scope="module")
def calculation_engine():
    url = os.environ.get("CALCULATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set CALCULATION_TEST_DATABASE_URL to a dedicated empty _test database")
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    assert engine.url.database.endswith("_test")
    assert not inspect(engine).get_table_names(), "Use an empty calculation test database"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "head")
        yield engine
        command.check(config)
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        command.check(config)
        command.downgrade(config, "base")
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE alembic_version")
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.mark.postgres
def test_idempotent_atomic_results_and_export(calculation_engine):
    from replenishment.calculation import calculate
    from replenishment.calculation.inputs import load_batch
    from replenishment.calculation.persistence import export_csv, run_calculation
    from replenishment.cli.import_excel import NORMALIZER_VERSION, import_workbook

    root = Path(__file__).resolve().parents[2]
    path = root / "docs/data/IEK/Ежемесячные продажи в количественном выражении за последние 2 года.xlsx"
    imported = import_workbook(calculation_engine, path, supplier="iek")
    with calculation_engine.connect() as connection:
        batch = load_batch(
            connection,
            metadata,
            planning_date="2026-09-22",
            source_selection=[
                {
                    "table": "demand_monthly_sales",
                    "normalizer_version": NORMALIZER_VERSION,
                    "sha256": imported["sha256"],
                }
            ],
        )
    assert imported and batch["series"]
    batch["series"] = batch["series"][:2]
    with ThreadPoolExecutor(max_workers=2) as pool:
        concurrent = list(pool.map(lambda _: run_calculation(calculation_engine, batch), range(2)))
    assert sorted(item["reused"] for item in concurrent) == [False, True]
    first = next(item for item in concurrent if not item["reused"])
    replay = run_calculation(calculation_engine, batch)
    assert replay["id"] == first["id"] and replay["reused"]
    with calculation_engine.connect() as connection:
        forecasts = metadata.tables["calculation_forecasts"]
        rows = connection.execute(select(forecasts).where(forecasts.c.run_id == first["id"])).all()
        assert len(rows) == 6
        exported = list(csv.DictReader(io.StringIO(export_csv(connection, metadata, first["id"], "iek"))))
        assert len(exported) == 2
        drafts = metadata.tables["calculation_drafts"]
        stored = connection.execute(select(drafts).where(drafts.c.run_id == first["id"])).mappings().all()
        assert [row["quantity"] for row in exported] == [
            "" if row["quantity"] is None else format(row["quantity"], "f")
            for row in sorted(stored, key=lambda row: row["series_id"])
        ]
        assert all(row["state"] == "blocked" for row in exported)

    from fastapi.testclient import TestClient

    from replenishment.api.app import create_app

    with TestClient(create_app(calculation_engine)) as client:
        params = {"run_id": str(first["id"]), "supplier": "iek", "page_size": 2}
        page = client.get("/api/v2/calculation/forecasts", params=params)
        assert page.status_code == 200 and page.json()["total"] == 6
        assert len(page.json()["items"]) == 2
        assert all(isinstance(row["quantity"], str) for row in page.json()["items"])
        blocked = client.get("/api/v2/calculation/drafts", params={**params, "state": "blocked"})
        assert blocked.status_code == 200 and blocked.json()["total"] == 2
        csv_response = client.get(f"/api/v2/calculation/runs/{first['id']}/export.csv?supplier=iek")
        assert csv_response.status_code == 200
        assert list(csv.DictReader(io.StringIO(csv_response.text))) == exported

    def invalid_result(value):
        result = calculate(value)
        result["forecasts"][0]["quantity"] = "-1"
        return result

    with pytest.raises(ValueError):
        run_calculation(calculation_engine, batch, rerun=True, calculator=invalid_result)

    def fail_draft_write(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO calculation_drafts"):
            raise RuntimeError("Injected write failure after forecasts were written")

    event.listen(calculation_engine, "before_cursor_execute", fail_draft_write)
    try:
        with pytest.raises(RuntimeError, match="Injected write failure"):
            run_calculation(calculation_engine, batch, rerun=True)
    finally:
        event.remove(calculation_engine, "before_cursor_execute", fail_draft_write)
    with calculation_engine.connect() as connection:
        runs = metadata.tables["calculation_runs"]
        states = connection.execute(select(runs.c.status)).scalars().all()
        assert sorted(states) == ["completed", "failed", "failed"]
        assert connection.execute(select(forecasts)).all() == rows


@pytest.mark.postgres
def test_api_creates_reuses_and_reruns_forecasts(calculation_engine):
    from fastapi.testclient import TestClient

    from replenishment.api.app import create_app
    from replenishment.cli.import_excel import NORMALIZER_VERSION, import_workbook

    root = Path(__file__).resolve().parents[2]
    path = (root / "docs/data/Systeme electric"
            / "Ежемесячные продажи в кол-м выражении SystemElectric 2024-2026.xlsx")
    imported = import_workbook(calculation_engine, path, supplier="systeme")
    source = {"table": "demand_monthly_sales", "sha256": imported["sha256"],
              "normalizer_version": NORMALIZER_VERSION}
    body = {"planning_date": "2026-09-22", "source_selection": [source], "supplier": "systeme"}
    with TestClient(create_app(calculation_engine)) as client:
        response = client.post("/api/v2/calculation/runs", json=body)
        assert response.status_code == 201, response.text
        first = response.json()
        assert first["status"] == "completed" and first["reused"] is False
        replay = client.post("/api/v2/calculation/runs", json=body)
        assert replay.status_code == 200
        assert replay.json() == {**first, "reused": True}
        rerun = client.post("/api/v2/calculation/runs", json={**body, "rerun": True})
        assert rerun.status_code == 201
        assert rerun.json()["id"] != first["id"] and rerun.json()["reused"] is False
        assert rerun.json()["fingerprint"] == first["fingerprint"]
        forecasts = client.get("/api/v2/calculation/forecasts", params={"run_id": first["id"]}).json()
        drafts = client.get("/api/v2/calculation/drafts", params={"run_id": first["id"]}).json()
        assert forecasts["total"] == 554 * 3 and drafts["total"] == 554
        assert all(row["supplier"] == "systeme" for row in forecasts["items"])
        assert all(isinstance(row["quantity"], str) for row in forecasts["items"] if row["status"] == "ok")
        assert client.get(f"/api/v2/calculation/runs/{first['id']}/export.csv").status_code == 200
        for invalid in (
            {**body, "supplier": "iek"},
            {**body, "source_selection": [{**source, "normalizer_version": "not-imported"}]},
            {**body, "source_selection": [{**source, "table": "inventory_monthly_stock"}]},
        ):
            response = client.post("/api/v2/calculation/runs", json=invalid)
            assert response.status_code == 422, response.text
        with calculation_engine.connect() as connection:
            runs = metadata.tables["calculation_runs"]
            saved = connection.execute(select(runs).where(runs.c.fingerprint == first["fingerprint"]))
            assert len(saved.all()) == 2  # Invalid requests never persist a run.


@pytest.mark.postgres
def test_source_selection_and_date_aware_purchasing_on_systeme_documents(calculation_engine):
    from copy import deepcopy
    from decimal import Decimal

    from replenishment.calculation.contracts import validate_batch
    from replenishment.calculation.forecasting import forecast_batch
    from replenishment.calculation.inputs import load_batch
    from replenishment.calculation.purchasing import build_drafts
    from replenishment.cli.calculate import SOURCE_TABLES
    from replenishment.cli.import_excel import NORMALIZER_VERSION, import_workbook

    root = Path(__file__).resolve().parents[2] / "docs/data/Systeme electric"
    selection = []
    for path in sorted(root.glob("*.xlsx")):
        imported = import_workbook(calculation_engine, path)
        selection.extend(
            {"table": table, "sha256": imported["sha256"], "normalizer_version": NORMALIZER_VERSION}
            for table in SOURCE_TABLES
        )
    with calculation_engine.connect() as connection:
        batch = load_batch(connection, metadata, "2026-09-22", source_selection=selection)
        replay = load_batch(connection, metadata, "2026-09-22", source_selection=selection * 2)
    validate_batch(batch)
    assert batch == replay
    assert len(batch["series"]) == 554  # Embedded report must not add a second forecast per SKU.
    assert all("inferred_unit" not in s for s in batch["series"])
    assert any(s["parameters"]["transaction_evidence"] for s in batch["series"])
    assert all(all(h["month"] < "2026-09-01" for h in s["history"]) for s in batch["series"])
    forecasts, bridges = forecast_batch(batch["series"], batch["planning_date"], include_bridge=True)
    drafts = build_drafts(batch, forecasts, bridges)
    usable = {d["series_id"] for d in drafts if d["state"] == "estimated"}
    assert usable
    series = next(
        s
        for s in batch["series"]
        if s["series_id"] in usable
        and any(Decimal(row["quantity"] or "0") > 0 for row in s["shipments"] or [])
    )
    single = {**batch, "series": [deepcopy(series)]}
    s = single["series"][0]
    s["inventory"].update(free="0", on_hand="0", reserved="0")  # Controlled transformation of actual stock.
    first = build_drafts(single, forecasts, bridges)[0]
    saved = deepcopy(s["shipments"])
    s["shipments"] = []
    removed = build_drafts(single, forecasts, bridges)[0]
    assert Decimal(removed["quantity"]) >= Decimal(first["quantity"])
    s["shipments"] = saved + deepcopy(saved)
    duplicate = build_drafts(single, forecasts, bridges)[0]
    assert duplicate["quantity"] == first["quantity"]
    for row in s["shipments"]:
        row["expected_on"] = "2026-12-31"
    late = build_drafts(single, forecasts, bridges)[0]
    assert late["components"]["first_shortage_date"] == "2026-09-22"
    assert Decimal(late["components"]["maximum_pre_arrival_shortfall"]) > 0
    s["inventory"] = None
    missing = build_drafts(single, forecasts, bridges)[0]
    assert missing["state"] == "blocked" and missing["components"]["raw_need"] is None
