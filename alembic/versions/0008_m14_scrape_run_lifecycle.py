"""M14 operational scrape run lifecycle.

Revision ID: 0008_m14_scrape_run_lifecycle
Revises: 0007_m12_rebuildable_projection
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_m14_scrape_run_lifecycle"
down_revision = "0007_m12_rebuildable_projection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("scope_key", sa.String(length=255), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("records_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_no_change", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_stale", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_disappeared", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_reappeared", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_scrape_runs_status",
        ),
        sa.CheckConstraint(
            "trigger_type IN ('MANUAL', 'SCHEDULED')",
            name="ck_scrape_runs_trigger_type",
        ),
    )
    op.create_index(
        "ix_scrape_runs_source_started_at",
        "scrape_runs",
        ["source", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_scrape_runs_source_started_at", table_name="scrape_runs")
    op.drop_table("scrape_runs")
