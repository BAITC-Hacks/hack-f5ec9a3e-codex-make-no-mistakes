"""Preserve databases created with the pre-merge scenario revision named 0002."""

import os

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from replenishment.schema import metadata


def reconcile(engine):
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        missing = {name for name in metadata.tables if name.startswith(("calculation_", "ordering_"))}
        expected = (set(metadata.tables) - missing) | {"alembic_version"}
        if tables != expected:
            raise ValueError("Expected the legacy source + scenario schema; database was not changed")
        version = connection.execute(text("SELECT version_num FROM alembic_version FOR UPDATE")).scalar_one()
        if version != "0002":
            raise ValueError("Expected legacy revision 0002; database was not changed")
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        with Operations.context(context):
            for revision in ("0002", "0003"):
                scripts.get_revision(revision).module.upgrade()
        if compare_metadata(context, metadata):
            raise ValueError("Schema differs from current metadata; transaction rolled back")
        connection.execute(text("UPDATE alembic_version SET version_num = '0004'"))


def main():
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        reconcile(engine)
        print("Legacy scenario database reconciled to 0004; existing rows preserved.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
