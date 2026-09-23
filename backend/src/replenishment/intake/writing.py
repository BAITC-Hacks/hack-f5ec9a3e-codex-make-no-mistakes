"""Public evidence capture and import completion ledger."""

from sqlalchemy import insert, select, text

from .models import DataFinding, SourceRow, SourceSheet, SourceWorkbook


def lock_import(connection):
    # ponytail: serialize workbook imports; use supplier locks if ingestion throughput becomes material.
    connection.execute(text("SELECT pg_advisory_xact_lock(724192026)"))


def existing_workbook(connection, digest, version, supplier):
    workbook = connection.execute(select(SourceWorkbook.id).where(SourceWorkbook.sha256 == digest)).scalar()
    if workbook is None:
        return None, False
    findings = (
        connection.execute(
            select(DataFinding.evidence).where(
                DataFinding.workbook_id == workbook, DataFinding.code == "import_complete"
            )
        )
        .scalars()
        .all()
    )
    if any(item["supplier"] != supplier for item in findings):
        raise ValueError("These exact workbook bytes have already been assigned to another supplier")
    return workbook, any(item["normalizer_version"] == version for item in findings)


def existing_sheets(connection, workbook):
    return dict(
        connection.execute(
            select(SourceSheet.name, SourceSheet.id).where(SourceSheet.workbook_id == workbook)
        ).all()
    )


def existing_rows(connection, sheet, numbers):
    return dict(
        connection.execute(
            select(SourceRow.row_number, SourceRow.id).where(
                SourceRow.sheet_id == sheet, SourceRow.row_number.in_(numbers)
            )
        ).all()
    )


def write_import_batch(connection, batch):
    for name, model in (
        ("workbooks", SourceWorkbook),
        ("sheets", SourceSheet),
        ("rows", SourceRow),
        ("findings", DataFinding),
    ):
        if batch.get(name):
            connection.execute(insert(model), batch[name])
