"""derive catalog completeness from persisted acquisition coverage

Revision ID: 0006_m9_catalog_coverage_proof
Revises: 0005_m8_catalog_completeness
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_m9_catalog_coverage_proof"
down_revision: Union[str, Sequence[str], None] = "0005_m8_catalog_completeness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "catalog_runs",
        sa.Column("run_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "catalog_runs",
        sa.Column("start_ref", sa.Text(), nullable=True),
    )

    # Existing M8 rows are historical manually-classified runs. Give them stable
    # compatibility keys/refs so the new columns can become non-null without
    # pretending they have M9 chunk-level coverage proof.
    op.execute(
        "UPDATE catalog_runs "
        "SET run_key = 'legacy:' || CAST(id AS VARCHAR) "
        "WHERE run_key IS NULL"
    )
    op.execute(
        "UPDATE catalog_runs "
        "SET start_ref = ("
        "  SELECT raw_evidence.source_url "
        "  FROM raw_evidence "
        "  WHERE raw_evidence.id = catalog_runs.evidence_id"
        ") "
        "WHERE start_ref IS NULL"
    )
    op.alter_column("catalog_runs", "run_key", nullable=False)
    op.alter_column("catalog_runs", "start_ref", nullable=False)
    op.alter_column("catalog_runs", "evidence_id", nullable=True)
    op.create_unique_constraint(
        "uq_catalog_runs_run_key",
        "catalog_runs",
        ["run_key"],
    )

    op.create_table(
        "catalog_run_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("catalog_run_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("requested_ref", sa.Text(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("next_ref", sa.Text(), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["catalog_run_id"],
            ["catalog_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["raw_evidence.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "catalog_run_id",
            "sequence",
            name="uq_catalog_run_chunks_run_sequence",
        ),
    )


def downgrade() -> None:
    # M9 runs without a single root evidence cannot satisfy M8's non-null
    # catalog_runs.evidence_id contract. They must be removed before downgrade.
    op.execute("DELETE FROM product_history WHERE catalog_run_id IN (SELECT id FROM catalog_runs WHERE evidence_id IS NULL)")
    op.execute("DELETE FROM catalog_runs WHERE evidence_id IS NULL")

    op.drop_table("catalog_run_chunks")
    op.drop_constraint("uq_catalog_runs_run_key", "catalog_runs", type_="unique")
    op.alter_column("catalog_runs", "evidence_id", nullable=False)
    op.drop_column("catalog_runs", "start_ref")
    op.drop_column("catalog_runs", "run_key")
