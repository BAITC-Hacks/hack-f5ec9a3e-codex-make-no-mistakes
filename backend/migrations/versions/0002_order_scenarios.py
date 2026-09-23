"""Immutable scenario revisions and attributed approvals.

Revision: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "orders_scenarios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_orders_scenarios_positive_revision")),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_orders_scenarios_nonempty_name")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders_scenarios")),
    )
    op.create_table(
        "orders_revisions",
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("overrides", postgresql.JSONB(), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_orders_revisions_positive_revision")),
        sa.ForeignKeyConstraint(["scenario_id"], ["orders_scenarios.id"],
                                name=op.f("fk_orders_revisions_scenario_id_orders_scenarios")),
        sa.PrimaryKeyConstraint("scenario_id", "revision", name=op.f("pk_orders_revisions")),
    )
    op.create_table(
        "orders_approvals",
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.String(200), nullable=False),
        sa.Column("acknowledge_scenario", sa.Boolean(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(trim(approved_by)) > 0", name=op.f("ck_orders_approvals_nonempty_actor")),
        sa.ForeignKeyConstraint(["scenario_id", "revision"],
                                ["orders_revisions.scenario_id", "orders_revisions.revision"],
                                name=op.f("fk_orders_approvals_scenario_id_orders_revisions")),
        sa.PrimaryKeyConstraint("scenario_id", "revision", name=op.f("pk_orders_approvals")),
    )
    op.execute("""
        CREATE FUNCTION reject_order_snapshot_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Order revisions and approvals are immutable';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("orders_revisions", "orders_approvals"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION reject_order_snapshot_change()")


def downgrade():
    op.drop_table("orders_approvals")
    op.drop_table("orders_revisions")
    op.drop_table("orders_scenarios")
    op.execute("DROP FUNCTION reject_order_snapshot_change()")
