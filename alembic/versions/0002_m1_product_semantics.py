"""generalize M0 book persistence to shared product semantics

Revision ID: 0002_m1_product_semantics
Revises: 0001_m0_persistence
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0002_m1_product_semantics"
down_revision: Union[str, Sequence[str], None] = "0001_m0_persistence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("book_observations", "product_observations")
    op.rename_table("books", "products")
    op.rename_table("book_history", "product_history")
    op.alter_column("product_history", "book_id", new_column_name="product_id")

    # Keep schema vocabulary aligned with the M1 domain vocabulary.
    op.execute(
        "ALTER TABLE product_observations "
        "RENAME CONSTRAINT uq_book_observation_evidence_extractor "
        "TO uq_product_observation_evidence_extractor"
    )
    op.execute(
        "ALTER TABLE products "
        "RENAME CONSTRAINT uq_books_source_canonical_url "
        "TO uq_products_source_canonical_url"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE products "
        "RENAME CONSTRAINT uq_products_source_canonical_url "
        "TO uq_books_source_canonical_url"
    )
    op.execute(
        "ALTER TABLE product_observations "
        "RENAME CONSTRAINT uq_product_observation_evidence_extractor "
        "TO uq_book_observation_evidence_extractor"
    )

    op.alter_column("product_history", "product_id", new_column_name="book_id")
    op.rename_table("product_history", "book_history")
    op.rename_table("products", "books")
    op.rename_table("product_observations", "book_observations")
