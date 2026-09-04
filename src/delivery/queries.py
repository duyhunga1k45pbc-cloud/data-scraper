from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.storage.models import ProductHistoryRow, ProductRow, ScrapeRunRow

from .representations import (
    history_representation,
    product_representation,
    run_representation,
)

MAX_PAGE_SIZE = 500


def _page(limit: int, offset: int) -> tuple[int, int]:
    if limit < 1 or limit > MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    return limit, offset


def list_current_products(
    session_factory: sessionmaker[Session],
    *,
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[dict, ...]:
    limit, offset = _page(limit, offset)
    stmt = select(ProductRow).order_by(ProductRow.source, ProductRow.identity_key)
    if source is not None:
        stmt = stmt.where(ProductRow.source == source)
    stmt = stmt.limit(limit).offset(offset)
    with session_factory() as session:
        rows = tuple(session.scalars(stmt))
    return tuple(product_representation(row) for row in rows)


def get_current_product(
    session_factory: sessionmaker[Session],
    *,
    source: str,
    identity_key: str,
) -> dict | None:
    stmt = select(ProductRow).where(
        ProductRow.source == source,
        ProductRow.identity_key == identity_key,
    )
    with session_factory() as session:
        row = session.scalar(stmt)
    return None if row is None else product_representation(row)


def get_product_history(
    session_factory: sessionmaker[Session],
    *,
    source: str,
    identity_key: str,
    limit: int = 100,
    offset: int = 0,
) -> tuple[dict, ...]:
    limit, offset = _page(limit, offset)
    stmt = (
        select(ProductHistoryRow)
        .where(
            ProductHistoryRow.source == source,
            ProductHistoryRow.identity_key == identity_key,
        )
        .order_by(ProductHistoryRow.changed_at, ProductHistoryRow.id)
        .limit(limit)
        .offset(offset)
    )
    with session_factory() as session:
        rows = tuple(session.scalars(stmt))
    return tuple(history_representation(row) for row in rows)


def list_runs(
    session_factory: sessionmaker[Session],
    *,
    source: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[dict, ...]:
    limit, offset = _page(limit, offset)
    stmt = select(ScrapeRunRow).order_by(ScrapeRunRow.started_at.desc(), ScrapeRunRow.id.desc())
    if source is not None:
        stmt = stmt.where(ScrapeRunRow.source == source)
    if status is not None:
        stmt = stmt.where(ScrapeRunRow.status == status)
    stmt = stmt.limit(limit).offset(offset)
    with session_factory() as session:
        rows = tuple(session.scalars(stmt))
    return tuple(run_representation(row) for row in rows)
