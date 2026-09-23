from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from replenishment.kernel.db import Base, Id


class SourceWorkbook(Base):
    __tablename__ = "intake_workbooks"
    __table_args__ = (
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint("byte_size = octet_length(content)", name="content_size"),
        CheckConstraint("sha256 = encode(sha256(content), 'hex')", name="content_hash"),
    )
    id: Mapped[Id]
    sha256: Mapped[str] = mapped_column(unique=True)
    original_path: Mapped[str]
    archive_name: Mapped[str | None]
    byte_size: Mapped[int]
    content: Mapped[bytes] = mapped_column(LargeBinary)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    capture_version: Mapped[str]


class SourceSheet(Base):
    __tablename__ = "intake_sheets"
    __table_args__ = (
        UniqueConstraint("workbook_id", "name"),
        CheckConstraint("position >= 0 AND reported_rows >= 0 AND reported_columns >= 0", name="dimensions"),
    )
    id: Mapped[Id]
    workbook_id: Mapped[UUID] = mapped_column(ForeignKey("intake_workbooks.id"))
    name: Mapped[str]
    position: Mapped[int]
    reported_rows: Mapped[int]
    reported_columns: Mapped[int]
    # Merged ranges, hidden state, header locations. Original bytes retain all Excel objects.
    layout: Mapped[dict] = mapped_column(JSONB, default=dict)


class SourceRow(Base):
    __tablename__ = "intake_rows"
    __table_args__ = (
        UniqueConstraint("sheet_id", "row_number"),
        CheckConstraint("row_number > 0", name="positive_row"),
        CheckConstraint("jsonb_typeof(cells) = 'object'", name="cells_object"),
    )
    id: Mapped[Id]
    sheet_id: Mapped[UUID] = mapped_column(ForeignKey("intake_sheets.id"))
    row_number: Mapped[int]
    # Column letters -> {type, value, formula, cached_value, number_format}.
    # Missing key = blank. Preserve Excel error tokens and numeric lexical values as strings.
    cells: Mapped[dict] = mapped_column(JSONB)


class DataFinding(Base):
    __tablename__ = "intake_findings"
    __table_args__ = (
        UniqueConstraint("workbook_id", "finding_key"),
        CheckConstraint("status IN ('open', 'resolved', 'accepted_limitation')", name="status"),
    )
    id: Mapped[Id]
    workbook_id: Mapped[UUID] = mapped_column(ForeignKey("intake_workbooks.id"))
    finding_key: Mapped[str]
    code: Mapped[str]
    evidence: Mapped[dict] = mapped_column(JSONB)  # sheet/ranges, observed and expected values
    description: Mapped[str]
    status: Mapped[str] = mapped_column(default="open")
    resolution: Mapped[str | None]
