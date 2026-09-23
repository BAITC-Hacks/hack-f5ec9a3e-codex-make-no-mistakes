"""Approval acceptance checks use only a dedicated, initially empty PostgreSQL database."""

import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError, OperationalError

from replenishment.api.app import create_app
from replenishment.cli.seed_demo import EMPLOYEE_IDS, RUN_ID, main, seed_demo
from replenishment.ordering.documents import DocumentError, quantity, validate_line
from replenishment.schema import metadata


@pytest.fixture(scope="module")
def ordering_engine():
    url = os.environ.get("ORDERING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ORDERING_TEST_DATABASE_URL to a dedicated empty _test database")
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    assert engine.url.database.endswith("_test")
    assert not inspect(engine).get_table_names(), "Use an empty ordering test database"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "head")
        yield engine
        command.check(config)
        with engine.connect() as connection:
            original = connection.execute(select(metadata.tables["calculation_drafts"])).all()
        command.downgrade(config, "0002")
        with engine.connect() as connection:
            assert connection.execute(select(metadata.tables["calculation_drafts"])).all() == original
        command.upgrade(config, "head")
        command.check(config)
        seed_demo(engine)
        with TestClient(create_app(engine)) as client:
            assert (
                client.post(
                    "/api/v2/order-documents",
                    json={"run_id": str(RUN_ID), "employee_id": str(EMPLOYEE_IDS[0])},
                ).status_code
                == 200
            )
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        command.check(config)
    finally:
        command.downgrade(config, "base")
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE alembic_version")
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def source_snapshot(engine):
    with engine.connect() as connection:
        return {
            name: connection.execute(select(table).order_by(table.c.id)).all()
            for name, table in metadata.tables.items()
            if name.startswith("calculation_")
        }


def clone_run(engine, *, status="completed", empty=False):
    run_id = uuid4()
    with engine.begin() as connection:
        for name in ("runs", "inputs", "forecasts", "drafts"):
            if empty and name != "runs":
                continue
            table = metadata.tables[f"calculation_{name}"]
            condition = table.c.id == RUN_ID if name == "runs" else table.c.run_id == RUN_ID
            rows = connection.execute(select(table).where(condition)).mappings().all()
            for row in rows:
                values = {**row, "id": uuid4(), "run_id": run_id}
                if name == "runs":
                    values.pop("run_id")
                    values.update(id=run_id, status=status)
                connection.execute(table.insert().values(**values))
    return run_id


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "1e18", "0.0000000000001", None])
def test_quantity_rejects_loss_or_invalid_values(value):
    with pytest.raises(DocumentError):
        quantity(value)


def test_quantity_preserves_full_precision_and_zero():
    assert quantity("999999999999999999.999999999999") == Decimal("999999999999999999.999999999999")
    assert quantity("0") == 0
    assert quantity("1.0000000000000") == 1


@pytest.mark.parametrize(
    "rules",
    [
        None,
        [
            {"kind": "minimum_shipment", "value": "100", "unit": "box", "interpretation_confirmed": False},
        ],
        [
            {"kind": "minimum_shipment", "value": "100", "unit": "piece", "interpretation_confirmed": True},
        ],
    ],
)
def test_manual_completion_never_invents_rule_interpretations_or_conversions(rules):
    validate_line(
        {
            "quantity": Decimal("3"),
            "purchase_unit": "box",
            "manual_completion_reason": "Employee confirmed three boxes",
            "recommendation": {"state": "blocked"},
            "input": {"snapshot": {"quantity_rules": rules}},
        },
        complete=True,
    )


@pytest.mark.postgres
def test_seed_edit_approve_and_atomic_rejections(ordering_engine, capsys):
    engine = ordering_engine
    main()  # Exercise the CLI entry point after migration, including printed fixture IDs.
    assert str(RUN_ID) in capsys.readouterr().out
    assert seed_demo(engine) == seed_demo(engine)
    original_sources = source_snapshot(engine)
    creator, editor = map(str, EMPLOYEE_IDS)
    with TestClient(create_app(engine)) as client:
        root = "/api/v2/order-documents"
        csv_url = f"/api/v2/calculation/runs/{RUN_ID}/export.csv"
        original_csv = client.get(csv_url).text
        assert len(client.get("/api/v2/employees").json()) == 2
        body = {"run_id": str(RUN_ID), "employee_id": creator}
        assert client.post(root, json={**body, "employee_id": str(uuid4())}).status_code == 404
        assert client.post(root, json={**body, "run_id": str(uuid4())}).status_code == 404
        for invalid_run in (clone_run(engine, status="running"), clone_run(engine, empty=True)):
            assert client.post(root, json={**body, "run_id": str(invalid_run)}).status_code == 409
        response = client.post(root, json=body)
        assert response.status_code == 200, response.text
        doc = response.json()
        url = f"{root}/{doc['id']}"
        assert len(doc["lines"]) == 3 and all(line["included"] for line in doc["lines"])
        assert client.post(root, json={**body, "employee_id": editor}).json() == doc
        a, b, blocked = [line["id"] for line in doc["lines"]]
        foreign_run = clone_run(engine)
        foreign_doc = client.post(root, json={**body, "run_id": str(foreign_run)}).json()
        foreign_line = foreign_doc["lines"][0]["id"]

        def rejected(payload, status, *, approve=False):
            before = client.get(url).json()
            request = {"employee_id": editor, "expected_revision": before["revision"], **payload}
            response = (
                client.post(url + "/approve", json=request) if approve else client.patch(url, json=request)
            )
            assert response.status_code == status, response.text
            assert client.get(url).json() == before

        rejected({}, 422, approve=True)  # Original blocked line remains unresolved.
        rejected({"employee_id": str(uuid4()), "note": "no"}, 404)
        rejected(
            {
                "lines": [{"id": a, "quantity": "20"}, {"id": foreign_line, "quantity": "10"}],
                "note": "must roll back",
            },
            404,
        )
        for value in ("-1", "NaN", "Infinity", "1e18", "0.0000000000001", None):
            rejected({"lines": [{"id": a, "quantity": value}]}, 422)
        for value in ("4", "7"):
            rejected({"lines": [{"id": a, "quantity": value}]}, 422)
        rejected({"lines": [{"id": a, "purchase_unit": "box"}]}, 422)
        rejected({"lines": [{"id": blocked, "purchase_unit": " "}]}, 422)
        rejected({"lines": [{"id": a, "sku": "changed"}]}, 422)
        rejected({"lines": [{"id": a}, {"id": a}]}, 422)
        rejected({"expected_revision": 99, "note": "stale"}, 409)

        def patch(**edits):
            before = client.get(url).json()
            response = client.patch(
                url, json={"employee_id": editor, "expected_revision": before["revision"], **edits}
            )
            assert response.status_code == 200, response.text
            assert response.json()["revision"] == before["revision"] + 1
            return response.json()

        patch(lines=[{"id": a, "quantity": "0"}])  # Zero bypasses positive minimum/multiple.
        patch(lines=[{"id": a, "quantity": "20"}], note="Reviewed synthetic demo")
        patch(lines=[{"id": b, "included": False}])
        patch(lines=[{"id": blocked, "quantity": "3", "purchase_unit": "box"}])
        rejected({}, 422, approve=True)  # Explicit quantity and unit alone do not resolve a blocker.
        patch(lines=[{"id": blocked, "manual_completion_reason": "   "}])
        rejected({}, 422, approve=True)
        patch(lines=[{"id": blocked, "manual_completion_reason": "Supplier confirmed three demo boxes"}])
        patch(lines=[{"id": value, "included": False} for value in (a, b, blocked)])
        rejected({}, 422, approve=True)
        patch(lines=[{"id": a, "included": True, "quantity": "0"}])
        rejected({}, 422, approve=True)  # Included zero alone is insufficient.
        doc = patch(lines=[{"id": a, "quantity": "20"}, {"id": blocked, "included": True}])
        rejected({"expected_revision": doc["revision"] - 1}, 409, approve=True)
        seed_demo(engine)
        assert client.get(url).json() == doc
        assert client.post(root, json=body).json() == doc
        response = client.post(
            url + "/approve", json={"employee_id": creator, "expected_revision": doc["revision"]}
        )
        assert response.status_code == 200, response.text
        approved = response.json()
        assert approved["status"] == "approved" and approved["revision"] == doc["revision"] + 1
        assert approved["creator"]["id"] == creator
        assert approved["last_editor"]["id"] == editor
        assert approved["approver"]["id"] == creator and approved["approved_at"]
        assert approved["lines"][0]["quantity"] == "20.000000000000"
        assert approved["lines"][0]["recommendation"]["quantity"] == "12.000000000000"
        assert approved["lines"][2]["recommendation"]["blocking_reason"]
        assert approved["lines"][2]["recommendation"]["quantity"] is None
        assert client.get(url).json() == approved
        assert client.get(csv_url).text == original_csv
        rejected({"note": "too late"}, 409)
        rejected({}, 409, approve=True)
        seed_demo(engine)
        assert client.post(root, json=body).json() == approved
        page = client.get(root, params={"run_id": str(RUN_ID), "status": "approved", "page_size": 1}).json()
        assert page["total"] == 1 and page["items"][0]["id"] == doc["id"]
        assert client.get(root, params={"run_id": str(RUN_ID), "status": "editable"}).json()["total"] == 0

    # Read through a fresh app/connection; attribution is persisted, not response-only.
    with TestClient(create_app(engine)) as fresh:
        assert fresh.get(url).json() == approved
    after = source_snapshot(engine)
    for table, rows in original_sources.items():
        assert all(row in after[table] for row in rows)
    for table_name in ("ordering_documents", "ordering_lines"):
        table = metadata.tables[table_name]
        with pytest.raises(IntegrityError), engine.begin() as connection:
            column = table.c.id if table_name == "ordering_documents" else table.c.document_id
            connection.execute(table.delete().where(column == doc["id"]))
        with pytest.raises(IntegrityError), engine.begin() as connection:
            column = table.c.id if table_name == "ordering_documents" else table.c.document_id
            values = {"note": "bypass"} if table_name == "ordering_documents" else {"quantity": "20"}
            connection.execute(table.update().where(column == doc["id"]).values(**values))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        table = metadata.tables["ordering_lines"]
        connection.execute(
            table.insert().values(
                document_id=foreign_doc["id"], run_id=RUN_ID, series_id="synthetic-1", included=True
            )
        )


@pytest.mark.postgres
def test_concurrent_edit_and_approval_share_revision(ordering_engine):
    engine = ordering_engine
    run_id = clone_run(engine)
    body = {"employee_id": str(EMPLOYEE_IDS[0]), "run_id": str(run_id)}
    root = "/api/v2/order-documents"
    barrier = Barrier(2)

    def create(_):
        with TestClient(create_app(engine)) as client:
            barrier.wait(timeout=10)
            response = client.post(root, json=body)
            assert response.status_code == 200
            return response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, duplicate = pool.map(create, range(2))
    assert first == duplicate
    url = f"{root}/{first['id']}"
    with TestClient(create_app(engine)) as client:
        response = client.patch(
            url,
            json={
                "employee_id": body["employee_id"],
                "expected_revision": 1,
                "lines": [{"id": first["lines"][2]["id"], "included": False}],
            },
        )
        assert response.status_code == 200

    def race(approve):
        with TestClient(create_app(engine)) as client:
            barrier.wait(timeout=10)
            payload = {"employee_id": body["employee_id"], "expected_revision": 2}
            return (
                client.post(url + "/approve", json=payload)
                if approve
                else client.patch(url, json={**payload, "note": "Concurrent edit"})
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(race, (False, True))) == [200, 409]
    with TestClient(create_app(engine)) as client:
        final = client.get(url).json()
        assert final["revision"] == 3
        if final["status"] == "editable":
            final = client.post(
                url + "/approve", json={"employee_id": body["employee_id"], "expected_revision": 3}
            ).json()
        assert final["status"] == "approved"  # Estimated line remains eligible, assumptions retained.
        assert final["lines"][1]["recommendation"]["assumptions"]


@pytest.mark.postgres
def test_database_failure_is_sanitized_and_rolls_back(ordering_engine):
    engine = ordering_engine
    run_id = clone_run(engine)
    employee_id = str(EMPLOYEE_IDS[0])
    with TestClient(create_app(engine)) as client:
        doc = client.post(
            "/api/v2/order-documents", json={"run_id": str(run_id), "employee_id": employee_id}
        ).json()
        url = f"/api/v2/order-documents/{doc['id']}"

        def fail(connection, cursor, statement, parameters, context, many):
            if statement.startswith("UPDATE ordering_documents"):
                raise OperationalError("secret database credentials", {}, Exception("secret"))

        event.listen(engine, "before_cursor_execute", fail)
        try:
            response = client.patch(
                url,
                json={
                    "employee_id": employee_id,
                    "expected_revision": 1,
                    "lines": [{"id": doc["lines"][0]["id"], "quantity": "20"}],
                },
            )
            assert response.status_code == 503
            assert response.json() == {"detail": "Database unavailable"}
        finally:
            event.remove(engine, "before_cursor_execute", fail)
        assert client.get(url).json() == doc
