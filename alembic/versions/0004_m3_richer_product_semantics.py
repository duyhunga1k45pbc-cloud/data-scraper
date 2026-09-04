"""add richer product pricing, category, SKU, and variant semantics

Revision ID: 0004_m3_richer_product_semantics
Revises: 0003_m2_multi_record_identity
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_m3_richer_product_semantics"
down_revision: Union[str, Sequence[str], None] = "0003_m2_multi_record_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_observations",
        sa.Column("compare_at_price_raw", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "product_observations",
        sa.Column("sku_raw", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "product_observations",
        sa.Column("categories_raw", sa.JSON(), nullable=True),
    )
    op.add_column(
        "product_observations",
        sa.Column("variants_raw", sa.JSON(), nullable=True),
    )
    op.add_column(
        "product_observations",
        sa.Column("compare_at_price", sa.Numeric(18, 2), nullable=True),
    )
    op.add_column(
        "product_observations",
        sa.Column("sku", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "product_observations",
        sa.Column("categories", sa.JSON(), nullable=True),
    )
    op.add_column(
        "product_observations",
        sa.Column("variants", sa.JSON(), nullable=True),
    )

    op.add_column(
        "products",
        sa.Column("compare_at_price", sa.Numeric(18, 2), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("sku", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("categories", sa.JSON(), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("variants", sa.JSON(), nullable=True),
    )

    op.execute(
        "UPDATE product_observations "
        "SET categories_raw = CASE "
        "WHEN category_raw IS NULL THEN '[]'::json "
        "ELSE json_build_array(category_raw) END, "
        "variants_raw = '[]'::json, "
        "categories = CASE "
        "WHEN category IS NULL THEN '[]'::json "
        "ELSE json_build_array(category) END, "
        "variants = '[]'::json"
    )
    op.execute(
        "UPDATE products "
        "SET categories = CASE "
        "WHEN category IS NULL THEN '[]'::json "
        "ELSE json_build_array(category) END, "
        "variants = '[]'::json"
    )

    op.alter_column("product_observations", "categories_raw", nullable=False)
    op.alter_column("product_observations", "variants_raw", nullable=False)
    op.alter_column("product_observations", "categories", nullable=False)
    op.alter_column("product_observations", "variants", nullable=False)
    op.alter_column("products", "categories", nullable=False)
    op.alter_column("products", "variants", nullable=False)


def downgrade() -> None:
    op.drop_column("products", "variants")
    op.drop_column("products", "categories")
    op.drop_column("products", "sku")
    op.drop_column("products", "compare_at_price")

    op.drop_column("product_observations", "variants")
    op.drop_column("product_observations", "categories")
    op.drop_column("product_observations", "sku")
    op.drop_column("product_observations", "compare_at_price")
    op.drop_column("product_observations", "variants_raw")
    op.drop_column("product_observations", "categories_raw")
    op.drop_column("product_observations", "sku_raw")
    op.drop_column("product_observations", "compare_at_price_raw")
