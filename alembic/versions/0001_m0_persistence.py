"""create M0 persistence tables

Revision ID: 0001_m0_persistence
Revises:
Create Date: 2026-09-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_m0_persistence"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "raw_evidence",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "book_observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("extractor_version", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title_raw", sa.Text(), nullable=True),
        sa.Column("price_raw", sa.String(length=128), nullable=True),
        sa.Column("availability_raw", sa.String(length=255), nullable=True),
        sa.Column("category_raw", sa.String(length=255), nullable=True),
        sa.Column("canonical_product_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("availability", sa.String(length=32), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("state_decision", sa.String(length=32), nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["raw_evidence.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evidence_id",
            "extractor_version",
            name="uq_book_observation_evidence_extractor",
        ),
    )

    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("canonical_product_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("availability", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_observation_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["accepted_observation_id"],
            ["book_observations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "canonical_product_url",
            name="uq_books_source_canonical_url",
        ),
    )

    op.create_table(
        "book_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("observation_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("previous_state", sa.JSON(), nullable=True),
        sa.Column("new_state", sa.JSON(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["book_observations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("book_history")
    op.drop_table("books")
    op.drop_table("book_observations")
    op.drop_table("raw_evidence")
