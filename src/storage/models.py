from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, synonym


class Base(DeclarativeBase):
    pass


class RawEvidenceRow(Base):
    __tablename__ = "raw_evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    body_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ProductObservationRow(Base):
    __tablename__ = "product_observations"
    __table_args__ = (
        UniqueConstraint(
            "evidence_id",
            "extractor_version",
            "identity_key",
            name="uq_product_observation_evidence_extractor_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evidence_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("raw_evidence.id", ondelete="RESTRICT"),
        nullable=False,
    )
    extractor_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    title_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_raw: Mapped[str | None] = mapped_column(String(128), nullable=True)
    currency_raw: Mapped[str | None] = mapped_column(String(32), nullable=True)
    availability_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)

    canonical_product_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)

    state_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class ProductRow(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "identity_key",
            name="uq_products_source_identity_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_product_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    availability: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_observation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("product_observations.id", ondelete="RESTRICT"),
        nullable=False,
    )


class ProductHistoryRow(Base):
    __tablename__ = "product_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    book_id = synonym("product_id")

    observation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("product_observations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_state: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


BookObservationRow = ProductObservationRow
BookRow = ProductRow
BookHistoryRow = ProductHistoryRow
