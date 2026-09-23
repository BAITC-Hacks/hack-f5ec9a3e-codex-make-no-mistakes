"""W1-W3 and revision isolation against an explicitly empty dedicated PostgreSQL database."""

import csv
import io
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from test_orders import application, planning_input

from replenishment.orders import writing

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def engine():
    url = os.environ.get("ORDERS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ORDERS_TEST_DATABASE_URL to a dedicated empty PostgreSQL _test database")
    if not (make_url(url).database or "").endswith("_test"):
        raise RuntimeError("Refusing to migrate a database without a _test suffix")
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    assert not inspect(engine).get_table_names(), "Use an empty orders test database"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "head")
        command.check(config)
        yield engine
        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
        command.upgrade(config, "head")
        command.check(config)
        command.downgrade(config, "base")
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE alembic_version"))
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture
def client(engine):
    with TestClient(application(engine)) as client:
        yield client


def create(client, input=None, name="Synthetic scenario"):
    response = client.post("/api/v1/scenarios", json={"name": name, "input": input or planning_input()})
    assert response.status_code == 201, response.text
    return response.json()


def approve(client, saved, **kwargs):
    return client.post(f"/api/v1/scenarios/{saved['id']}/approve", json={
        "expected_revision": saved["revision"], "approved_by": "Local manager",
        "acknowledge_scenario": True, **kwargs,
    })


def test_save_restart_override_approval_and_exact_export(client, engine):
    saved = create(client)
    path = f"/api/v1/scenarios/{saved['id']}"
    # Dispose connections and build a fresh app/engine: state must live in PostgreSQL.
    restarted_engine = create_engine(engine.url)
    try:
        with TestClient(application(restarted_engine)) as restarted:
            assert restarted.get(path).json() == saved
    finally:
        restarted_engine.dispose()
    assert client.get(path + "/export?expected_revision=1").status_code == 409
    assert approve(client, saved, acknowledge_scenario=False).status_code == 409
    assert approve(client, saved).status_code == 200
    update = client.put(path, json={
        "expected_revision": 1, "name": saved["name"], "input": saved["input"],
        "overrides": [{"row_id": "item-1", "quantity": "24.125", "reason": "Manager reviewed quantity"}],
    })
    assert update.status_code == 200, update.text
    revised = update.json()
    assert revised["revision"] == 2 and revised["approved_revision"] is None
    assert revised["result"]["rows"][0]["recommended_quantity"] == "18"
    assert client.get(path + "/export?expected_revision=1").status_code == 409
    assert client.get(path + "/export?expected_revision=2").status_code == 409
    assert approve(client, saved).status_code == 409
    assert approve(client, revised).status_code == 200
    exported = client.get(path + "/export?expected_revision=2")
    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert rows[0]["recommended_quantity"] == "18" and rows[0]["approved_quantity"] == "24.125"
    assert rows[0]["override_reason"] == "Manager reviewed quantity"
    assert rows[0]["approved_revision"] == "2" and rows[0]["order_basis"] == "scenario"
    assert "fixture-row" in rows[0]["sources"]
    with engine.connect() as connection:
        revisions = connection.execute(text(
            'SELECT revision, input, result, overrides FROM orders_revisions '
            'WHERE scenario_id = :id ORDER BY revision'
        ), {"id": UUID(saved["id"])}).mappings().all()
        assert len(revisions) == 2 and revisions[0]["overrides"] == []
        assert revisions[0]["input"] == saved["input"]
        assert revisions[0]["result"] == saved["result"]
        assert connection.scalar(text("SELECT count(*) FROM orders_approvals WHERE scenario_id = :id"),
                                 {"id": UUID(saved["id"])}) == 2
    items = client.get("/api/v1/scenarios").json()["items"]
    current = next(item for item in items if item["id"] == saved["id"])
    assert current["approved_revision"] == 2


def test_blocked_rows_unknown_duplicate_overrides_and_missing_scenarios(client):
    data = planning_input()
    data["rows"][0]["free_stock"] = None
    blocked = create(client, data)
    path = f"/api/v1/scenarios/{blocked['id']}"
    assert blocked["result"]["rows"][0]["status"] == "needs_input"
    assert approve(client, blocked).status_code == 409
    for overrides in ([{"row_id": "item-1", "quantity": "2", "reason": "Cannot fix unknown stock"}],
                      [{"row_id": "unknown", "quantity": "2", "reason": "Unknown"}]):
        assert client.put(path, json={"expected_revision": 1, "name": "Blocked", "input": data,
                                     "overrides": overrides}).status_code == 422
    saved = create(client)
    override = {"row_id": "item-1", "quantity": "2", "reason": "Duplicate"}
    assert client.put(f"/api/v1/scenarios/{saved['id']}", json={
        "expected_revision": 1, "name": "Duplicate", "input": planning_input(),
        "overrides": [override, override],
    }).status_code == 422
    assert client.get(f"/api/v1/scenarios/{uuid4()}").status_code == 404


def test_stale_simultaneous_updates_have_one_winner(client, engine):
    saved = create(client)

    def update():
        try:
            return writing.update_scenario(
                engine, UUID(saved["id"]), expected_revision=1, name="Concurrent",
                input=saved["input"], result=saved["result"], overrides=[],
            )["revision"]
        except writing.ScenarioConflict:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: update(), range(2)))
    assert results.count(2) == 1 and results.count("stale") == 1


def test_snapshots_and_approvals_cannot_be_rewritten(client, engine):
    saved = create(client)
    assert approve(client, saved).status_code == 200
    for statement in ("UPDATE orders_revisions SET result = '{}' WHERE scenario_id = :id",
                      "DELETE FROM orders_revisions WHERE scenario_id = :id",
                      "UPDATE orders_approvals SET approved_by = 'other' WHERE scenario_id = :id",
                      "DELETE FROM orders_approvals WHERE scenario_id = :id"):
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(text(statement), {"id": UUID(saved["id"])})


def test_export_groups_suppliers_and_neutralizes_formulas(client):
    data = planning_input()
    data["rows"][0].update({"supplier": "Zulu", "sku": "=1+1", "name": " \t@SUM(A1)",
                            "purchase_unit": "+piece", "warehouse": "Almaty"})
    data["rows"].append({**data["rows"][0], "row_id": "item-2", "supplier": "Alpha", "sku": "002"})
    saved = create(client, data, name="=SUM(A1)")
    assert approve(client, saved, approved_by="\t=actor").status_code == 200
    response = client.get(f"/api/v1/scenarios/{saved['id']}/export?expected_revision=1")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert [row["supplier"] for row in rows] == ["Alpha", "Zulu"]
    assert rows[1]["sku"] == "'=1+1"
    assert rows[0]["name"].startswith("'")
    assert rows[0]["purchase_unit"] == "'+piece"
    assert rows[0]["approved_by"].startswith("'") and rows[0]["scenario_name"].startswith("'")
