"""M15 abandoned-run recovery and retry lineage.

Revision ID: 0009_m15_run_recovery_retry
Revises: 0008_m14_scrape_run_lifecycle
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_m15_run_recovery_retry"
down_revision = "0008_m14_scrape_run_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scrape_runs",
        sa.Column("retry_of_run_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "scrape_runs",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "scrape_runs",
        sa.Column(
            "accounting_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        "UPDATE scrape_runs SET accounting_complete = TRUE "
        "WHERE status IN ('SUCCEEDED', 'FAILED')"
    )
    op.create_foreign_key(
        "fk_scrape_runs_retry_of_run_id",
        "scrape_runs",
        "scrape_runs",
        ["retry_of_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_scrape_runs_retry_of_run_id",
        "scrape_runs",
        ["retry_of_run_id"],
    )
    op.create_check_constraint(
        "ck_scrape_runs_attempt",
        "scrape_runs",
        "attempt >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_scrape_runs_attempt", "scrape_runs", type_="check")
    op.drop_constraint(
        "uq_scrape_runs_retry_of_run_id", "scrape_runs", type_="unique"
    )
    op.drop_constraint(
        "fk_scrape_runs_retry_of_run_id", "scrape_runs", type_="foreignkey"
    )
    op.drop_column("scrape_runs", "accounting_complete")
    op.drop_column("scrape_runs", "attempt")
    op.drop_column("scrape_runs", "retry_of_run_id")
