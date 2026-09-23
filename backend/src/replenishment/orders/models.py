"""Order workflow persistence; no dependencies on calculation or source domains."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from replenishment.kernel.db import Base, Id


class Scenario(Base):
    __tablename__ = "orders_scenarios"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("length(trim(name)) > 0", name="nonempty_name"),
    )

    id: Mapped[Id]
    name: Mapped[str] = mapped_column(String(200))
    revision: Mapped[int]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScenarioRevision(Base):
    __tablename__ = "orders_revisions"
    __table_args__ = (CheckConstraint("revision >= 1", name="positive_revision"),)

    scenario_id: Mapped[UUID] = mapped_column(ForeignKey("orders_scenarios.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    overrides: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScenarioApproval(Base):
    __tablename__ = "orders_approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scenario_id", "revision"], ["orders_revisions.scenario_id", "orders_revisions.revision"]
        ),
        CheckConstraint("length(trim(approved_by)) > 0", name="nonempty_actor"),
    )

    scenario_id: Mapped[UUID] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(primary_key=True)
    approved_by: Mapped[str] = mapped_column(String(200))
    acknowledge_scenario: Mapped[bool]
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
