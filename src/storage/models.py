from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
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




class CatalogRunRow(Base):
    __tablename__ = "catalog_runs"
    __table_args__ = (
        UniqueConstraint(
            "evidence_id",
            "source",
            "scope_key",
            name="uq_catalog_run_evidence_source_scope",
        ),
        UniqueConstraint("run_key", name="uq_catalog_runs_run_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # M8 compatibility/root anchor. M9 proof is the 1:N catalog_run_chunks relation.
    evidence_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("raw_evidence.id", ondelete="RESTRICT"),
        nullable=True,
    )
    run_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(255), nullable=False)
    start_ref: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)


class CatalogRunChunkRow(Base):
    __tablename__ = "catalog_run_chunks"
    __table_args__ = (
        UniqueConstraint(
            "catalog_run_id",
            "sequence",
            name="uq_catalog_run_chunks_run_sequence",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("catalog_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_ref: Mapped[str] = mapped_column(Text, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("raw_evidence.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    next_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(255), nullable=True)

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
    compare_at_price_raw: Mapped[str | None] = mapped_column(String(128), nullable=True)
    currency_raw: Mapped[str | None] = mapped_column(String(32), nullable=True)
    availability_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sku_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    categories_raw: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    variants_raw: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)

    canonical_product_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    compare_at_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    categories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    variants: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)

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
    compare_at_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    availability: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    categories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    variants: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    presence_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    presence_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_observation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("product_observations.id", ondelete="RESTRICT"),
        nullable=False,
    )


class ProductHistoryRow(Base):
    __tablename__ = "product_history"
    __table_args__ = (
        CheckConstraint(
            "(observation_id IS NOT NULL AND catalog_run_id IS NULL) OR "
            "(observation_id IS NULL AND catalog_run_id IS NOT NULL)",
            name="ck_product_history_exactly_one_provenance",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # M12: history is the semantic ledger, not part of the mutable projection.
    # Stable domain identity is persisted directly so the products projection can
    # be detached/deleted and rebuilt without deleting history. product_id is a
    # nullable convenience link to the current materialized projection row.
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_key: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )
    book_id = synonym("product_id")

    observation_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("product_observations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    catalog_run_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("catalog_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_state: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScrapeRunRow(Base):
    __tablename__ = "scrape_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_scrape_runs_status",
        ),
        CheckConstraint(
            "trigger_type IN ('MANUAL', 'SCHEDULED')",
            name="ck_scrape_runs_trigger_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    records_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_no_change: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_stale: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_disappeared: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_reappeared: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


BookObservationRow = ProductObservationRow
BookRow = ProductRow
BookHistoryRow = ProductHistoryRow
