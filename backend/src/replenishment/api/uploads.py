"""Bounded upload transport for the existing atomic source importer."""

import csv
from io import BytesIO, StringIO
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from replenishment.browsing.tables import TABLES, filter_conditions, json_value, projection
from replenishment.cli.import_excel import import_workbook
from replenishment.intake.adapters.csv import CSV_COLUMNS

MAX_UPLOAD = 64 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_FILES = 30


def checked_zip(content):
    archive = ZipFile(BytesIO(content))
    if len(archive.infolist()) > 5000 or sum(i.file_size for i in archive.infolist()) > MAX_EXPANDED:
        archive.close()
        raise ValueError("Archive expands beyond the 512 MB / 5000 entry limit")
    if any(i.flag_bits & 1 for i in archive.infolist()):
        archive.close()
        raise ValueError("Encrypted archives are not supported")
    return archive


def upload_sources(engine, content, filename, supplier):
    filename = PurePosixPath(filename.replace("\\", "/")).name
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in {".xlsx", ".csv", ".zip"}:
        raise ValueError("Choose an XLSX, UTF-8 CSV or ZIP containing XLSX/CSV files")
    sources = []
    if suffix == ".zip":
        with checked_zip(content) as archive:
            members = [i for i in archive.infolist() if not i.is_dir()]
            if not members or len(members) > MAX_FILES:
                raise ValueError("ZIP must contain 1–30 XLSX/CSV files")
            for member in members:
                name = member.filename
                if not member.flag_bits & 0x800:
                    try:
                        name = name.encode("cp437").decode("cp866")
                    except UnicodeEncodeError:
                        pass  # Python may already decode the Unicode-path extra field.
                path = PurePosixPath(name.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts or path.suffix.lower() not in {".xlsx", ".csv"}:
                    raise ValueError(f"Unsupported ZIP entry: {name}")
                if member.file_size > MAX_UPLOAD:
                    raise ValueError(f"ZIP entry exceeds 64 MB: {name}")
                sources.append((f"{filename}/{path}", archive.read(member)))
    else:
        sources.append((filename, content))
    results = []
    for name, data in sources:
        try:
            if name.lower().endswith(".xlsx"):
                with checked_zip(data):
                    pass
            result = import_workbook(engine, name, supplier, content=data)
            results.append(result)
        except (ValueError, BadZipFile, ParseError, KeyError, IndexError, OverflowError) as error:
            results.append({"path": name, "status": "failed", "error": str(error) or "Invalid workbook"})
        except SQLAlchemyError:
            results.append({"path": name, "status": "failed",
                            "error": "Database import failed; no rows from this workbook were saved"})
    return {"results": results}


def csv_cell(value):
    value = json_value(value)
    # Spreadsheet formula injection protection; numeric negative quantities remain numeric.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        try:
            float(value)
        except ValueError:
            return "'" + value
    return value


def create_uploads_router(engine, metadata):
    router = APIRouter(prefix="/api/v1/sources", tags=["source uploads"])

    @router.post("/upload")
    async def upload(request: Request, filename: str = Query(min_length=1, max_length=255),
                     supplier: Literal["iek", "systeme"] | None = None):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_UPLOAD:
                raise HTTPException(413, "Maximum upload size is 64 MB")
        if not content:
            raise HTTPException(422, "File is empty")
        try:
            return await run_in_threadpool(upload_sources, engine, bytes(content), filename, supplier)
        except (ValueError, BadZipFile) as error:
            raise HTTPException(422, str(error)) from error

    @router.get("/template.csv")
    def template():
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(CSV_COLUMNS)
        writer.writerows([
            ["monthly_sales", "000123", "Пример товара", "2026-08-01", "20", "шт", "Алматы", "", ""],
            ["monthly_stock", "000123", "Пример товара", "2026-09-01", "5", "шт", "Алматы", "", ""],
            ["incoming", "000123", "Пример товара", "2026-10-01", "10", "шт", "Алматы", "PO-001", ""],
        ])
        return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="import-template.csv"'})

    @router.get("/export/{table}.csv")
    def export(table: str, workbook_id: UUID | None = None, supplier_id: UUID | None = None,
               q: str | None = Query(default=None, max_length=200)):
        if table not in TABLES or table in {"catalog", "suppliers", "warehouses", "workbooks"}:
            raise HTTPException(422, "Choose a source observation table")
        joined, columns = projection(metadata, table)
        statement = select(*(c.label(name) for name, c in columns.items())).select_from(joined)
        try:
            conditions = filter_conditions(columns, table,
                                           {"workbook_id": workbook_id, "supplier_id": supplier_id}, q)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        statement = statement.where(*conditions).order_by(columns["id"])

        def rows():
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(columns)
            yield "\ufeff" + output.getvalue()
            with engine.connect() as connection:
                for row in connection.execution_options(yield_per=500).execute(statement).mappings():
                    output.seek(0)
                    output.truncate()
                    writer.writerow(csv_cell(row[key]) for key in columns)
                    yield output.getvalue()

        return StreamingResponse(rows(), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{table}.csv"'})

    return router
