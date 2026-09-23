"""The branch migration repair preserves existing scenario data atomically."""

import os
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from replenishment.cli.reconcile_legacy_scenarios import reconcile
from replenishment.schema import metadata


@pytest.mark.postgres
def test_legacy_reconcile_preserves_scenarios():
    url = os.environ.get("LEGACY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set LEGACY_TEST_DATABASE_URL to an empty _test database")
    engine = create_engine(url)
    assert engine.url.database.endswith("_test")
    assert not inspect(engine).get_table_names()
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    scenario_id = uuid4()
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            for revision in ("0001", "0004"):
                scripts.get_revision(revision).module.upgrade()
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0002')"))
        connection.execute(metadata.tables["orders_scenarios"].insert().values(
            id=scenario_id, name="Preserved order", revision=1,
        ))
    reconcile(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0004"
        assert connection.execute(text("SELECT name FROM orders_scenarios")).scalar_one() == "Preserved order"
    with pytest.raises(ValueError, match="Expected the legacy"):
        reconcile(engine)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            for revision in ("0004", "0003", "0002", "0001"):
                scripts.get_revision(revision).module.downgrade()
        connection.execute(text("DROP TABLE alembic_version"))
    engine.dispose()
