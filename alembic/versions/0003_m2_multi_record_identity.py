"""support multi-record evidence and source-record identity

Revision ID: 0003_m2_multi_record_identity
Revises: 0002_m1_product_semantics
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_m2_multi_record_identity"
down_revision: Union[str, Sequence[str], None] = "0002_m1_product_semantics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_observations",
        sa.Column("identity_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "product_observations",
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "product_observations",
        sa.Column("currency_raw", sa.String(length=32), nullable=True),
    )

    op.add_column(
        "products",
        sa.Column("identity_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
    )

    op.execute(
        "UPDATE product_observations "
        "SET identity_key = 'url:' || COALESCE(canonical_product_url, source_url)"
    )
    op.execute(
        "UPDATE products "
        "SET identity_key = 'url:' || canonical_product_url"
    )

    op.alter_column("product_observations", "identity_key", nullable=False)
    op.alter_column("products", "identity_key", nullable=False)
    op.alter_column("products", "canonical_product_url", nullable=True)

    op.drop_constraint(
        "uq_product_observation_evidence_extractor",
        "product_observations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_product_observation_evidence_extractor_identity",
        "product_observations",
        ["evidence_id", "extractor_version", "identity_key"],
    )

    op.drop_constraint(
        "uq_products_source_canonical_url",
        "products",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_products_source_identity_key",
        "products",
        ["source", "identity_key"],
    )


def downgrade() -> None:
    # M2 source records may not have product URLs. Remove those records before
    # restoring the M1 URL-only identity contract.
    op.execute(
        "DELETE FROM product_history WHERE product_id IN "
        "(SELECT id FROM products WHERE source_record_id IS NOT NULL)"
    )
    op.execute("DELETE FROM products WHERE source_record_id IS NOT NULL")
    op.execute("DELETE FROM product_observations WHERE source_record_id IS NOT NULL")

    op.drop_constraint(
        "uq_products_source_identity_key",
        "products",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_products_source_canonical_url",
        "products",
        ["source", "canonical_product_url"],
    )

    op.drop_constraint(
        "uq_product_observation_evidence_extractor_identity",
        "product_observations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_product_observation_evidence_extractor",
        "product_observations",
        ["evidence_id", "extractor_version"],
    )

    op.alter_column("products", "canonical_product_url", nullable=False)

    op.drop_column("products", "source_record_id")
    op.drop_column("products", "identity_key")
    op.drop_column("product_observations", "currency_raw")
    op.drop_column("product_observations", "source_record_id")
    op.drop_column("product_observations", "identity_key")
