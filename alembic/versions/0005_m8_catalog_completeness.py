"""add catalog completeness and product presence semantics

Revision ID: 0005_m8_catalog_completeness
Revises: 0004_m3_richer_product_semantics
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_m8_catalog_completeness"
down_revision: Union[str, Sequence[str], None] = "0004_m3_richer_product_semantics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("scope_key", sa.String(length=255), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["raw_evidence.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evidence_id",
            "source",
            "scope_key",
            name="uq_catalog_run_evidence_source_scope",
        ),
    )

    op.add_column(
        "products",
        sa.Column("presence_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("presence_observed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE products "
        "SET presence_status = 'ACTIVE', presence_observed_at = observed_at"
    )
    op.alter_column("products", "presence_status", nullable=False)
    op.alter_column("products", "presence_observed_at", nullable=False)

    op.alter_column("product_history", "observation_id", nullable=True)
    op.add_column(
        "product_history",
        sa.Column("catalog_run_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_product_history_catalog_run_id",
        "product_history",
        "catalog_runs",
        ["catalog_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_product_history_exactly_one_provenance",
        "product_history",
        "(observation_id IS NOT NULL AND catalog_run_id IS NULL) OR "
        "(observation_id IS NULL AND catalog_run_id IS NOT NULL)",
    )


def downgrade() -> None:
    # M8 disappearance history has catalog-run provenance rather than a product
    # observation. It cannot satisfy the pre-M8 non-null observation contract.
    op.execute("DELETE FROM product_history WHERE observation_id IS NULL")

    op.drop_constraint(
        "ck_product_history_exactly_one_provenance",
        "product_history",
        type_="check",
    )
    op.drop_constraint(
        "fk_product_history_catalog_run_id",
        "product_history",
        type_="foreignkey",
    )
    op.drop_column("product_history", "catalog_run_id")
    op.alter_column("product_history", "observation_id", nullable=False)

    op.drop_column("products", "presence_observed_at")
    op.drop_column("products", "presence_status")
    op.drop_table("catalog_runs")
