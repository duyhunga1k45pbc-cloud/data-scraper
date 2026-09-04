"""decouple semantic history from rebuildable product projection

Revision ID: 0007_m12_rebuildable_projection
Revises: 0006_m9_catalog_coverage_proof
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_m12_rebuildable_projection"
down_revision: Union[str, Sequence[str], None] = "0006_m9_catalog_coverage_proof"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _product_fk_name() -> str | None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for foreign_key in inspector.get_foreign_keys("product_history"):
        constrained = foreign_key.get("constrained_columns") or []
        referred = foreign_key.get("referred_table")
        if constrained == ["product_id"] and referred == "products":
            return foreign_key.get("name")
    return None


def upgrade() -> None:
    op.add_column(
        "product_history",
        sa.Column("source", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "product_history",
        sa.Column("identity_key", sa.Text(), nullable=True),
    )

    # Backfill stable domain identity before relaxing the projection FK.
    op.execute(
        "UPDATE product_history AS h "
        "SET source = p.source, identity_key = p.identity_key "
        "FROM products AS p "
        "WHERE h.product_id = p.id"
    )
    op.alter_column("product_history", "source", nullable=False)
    op.alter_column("product_history", "identity_key", nullable=False)

    old_fk = _product_fk_name()
    if old_fk is not None:
        op.drop_constraint(old_fk, "product_history", type_="foreignkey")

    op.alter_column("product_history", "product_id", nullable=True)
    op.create_foreign_key(
        "fk_product_history_product_id",
        "product_history",
        "products",
        ["product_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_product_history_source_identity_id",
        "product_history",
        ["source", "identity_key", "id"],
        unique=False,
    )


def downgrade() -> None:
    # A history row detached from products cannot satisfy the pre-M12 contract.
    # Refuse to fabricate a projection link during downgrade.
    bind = op.get_bind()
    detached = bind.scalar(
        sa.text("SELECT COUNT(*) FROM product_history WHERE product_id IS NULL")
    )
    if detached:
        raise RuntimeError(
            "cannot downgrade M12 while detached product_history rows exist; "
            "relink or remove them first"
        )

    op.drop_index("ix_product_history_source_identity_id", table_name="product_history")
    op.drop_constraint(
        "fk_product_history_product_id",
        "product_history",
        type_="foreignkey",
    )
    op.alter_column("product_history", "product_id", nullable=False)
    op.create_foreign_key(
        "fk_product_history_product_id_pre_m12",
        "product_history",
        "products",
        ["product_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("product_history", "identity_key")
    op.drop_column("product_history", "source")
