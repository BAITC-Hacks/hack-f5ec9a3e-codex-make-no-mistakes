"""employee_order_documents

Revision: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ordering_employees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ordering_employees")),
    )
    op.create_table(
        "ordering_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.Column("last_editor_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'approved' AND approver_id IS NOT NULL AND approved_at IS NOT NULL) OR "
            "(status = 'editable' AND approver_id IS NULL AND approved_at IS NULL)",
            name=op.f("ck_ordering_documents_approval"),
        ),
        sa.CheckConstraint("status IN ('editable', 'approved')", name=op.f("ck_ordering_documents_status")),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_ordering_documents_revision")),
        sa.ForeignKeyConstraint(
            ["approver_id"],
            ["ordering_employees.id"],
            name=op.f("fk_ordering_documents_approver_id_ordering_employees"),
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["ordering_employees.id"],
            name=op.f("fk_ordering_documents_creator_id_ordering_employees"),
        ),
        sa.ForeignKeyConstraint(
            ["last_editor_id"],
            ["ordering_employees.id"],
            name=op.f("fk_ordering_documents_last_editor_id_ordering_employees"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["calculation_runs.id"], name=op.f("fk_ordering_documents_run_id_calculation_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ordering_documents")),
        sa.UniqueConstraint("id", "run_id", name=op.f("uq_ordering_documents_id")),
        sa.UniqueConstraint("run_id", name=op.f("uq_ordering_documents_run_id")),
    )
    op.create_table(
        "ordering_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("series_id", sa.String(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=30, scale=12), nullable=True),
        sa.Column("purchase_unit", sa.String(), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("manual_completion_reason", sa.String(), nullable=True),
        sa.CheckConstraint(
            "quantity >= 0 AND quantity < 1e18 AND quantity <> 'NaN'::numeric",
            name=op.f("ck_ordering_lines_quantity"),
        ),
        sa.CheckConstraint(
            "purchase_unit IS NULL OR length(trim(purchase_unit)) > 0", name=op.f("ck_ordering_lines_unit")
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "run_id"],
            ["ordering_documents.id", "ordering_documents.run_id"],
            name=op.f("fk_ordering_lines_document_id_ordering_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "series_id"],
            ["calculation_drafts.run_id", "calculation_drafts.series_id"],
            name=op.f("fk_ordering_lines_run_id_calculation_drafts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ordering_lines")),
        sa.UniqueConstraint("document_id", "series_id", name=op.f("uq_ordering_lines_document_id")),
    )
    op.execute("""
        CREATE FUNCTION ordering_guard_document() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status = 'approved' THEN
                RAISE EXCEPTION 'Approved document is permanently locked' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER ordering_document_lock BEFORE UPDATE OR DELETE ON ordering_documents
        FOR EACH ROW EXECUTE FUNCTION ordering_guard_document();
        CREATE FUNCTION ordering_guard_line() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_id uuid; parent_status text;
        BEGIN
            IF TG_OP = 'UPDATE' AND (NEW.document_id, NEW.run_id, NEW.series_id)
                IS DISTINCT FROM (OLD.document_id, OLD.run_id, OLD.series_id) THEN
                RAISE EXCEPTION 'Line source is fixed' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN parent_id := OLD.document_id;
            ELSE parent_id := NEW.document_id; END IF;
            SELECT status INTO parent_status FROM ordering_documents WHERE id = parent_id FOR UPDATE;
            IF parent_status = 'approved' THEN
                RAISE EXCEPTION 'Approved document is permanently locked' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER ordering_line_lock BEFORE INSERT OR UPDATE OR DELETE ON ordering_lines
        FOR EACH ROW EXECUTE FUNCTION ordering_guard_line();
    """)


def downgrade():
    op.drop_table("ordering_lines")
    op.drop_table("ordering_documents")
    op.drop_table("ordering_employees")
    op.execute("DROP FUNCTION ordering_guard_line()")
    op.execute("DROP FUNCTION ordering_guard_document()")
