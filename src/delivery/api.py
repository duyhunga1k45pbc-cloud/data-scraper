from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .queries import (
    MAX_PAGE_SIZE,
    get_current_product,
    get_product_history,
    list_current_products,
    list_runs,
)


def create_app(
    *,
    session_factory: sessionmaker[Session] | None = None,
    database_url: str | None = None,
) -> FastAPI:
    """Create the read-only M17 delivery API.

    The delivery layer only reads trusted projection/history and operational run rows.
    It does not scrape, normalize, validate, or mutate state.
    """

    engine = None
    if session_factory is None:
        resolved_url = database_url or os.getenv("DATABASE_URL")
        if not resolved_url:
            raise RuntimeError("DATABASE_URL is required to create the delivery API")
        engine = create_engine(resolved_url, future=True)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    app = FastAPI(title="data-scraper delivery API", version="0.15.0")
    app.state.session_factory = session_factory
    app.state.delivery_engine = engine

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/products")
    def products(
        source: str | None = None,
        limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
        offset: int = Query(0, ge=0),
    ) -> dict:
        items = list_current_products(
            session_factory,
            source=source,
            limit=limit,
            offset=offset,
        )
        return {
            "items": items,
            "limit": limit,
            "offset": offset,
            "returned": len(items),
        }

    @app.get("/product")
    def product(source: str, identity_key: str) -> dict:
        item = get_current_product(
            session_factory,
            source=source,
            identity_key=identity_key,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="product not found")
        return item

    @app.get("/product/history")
    def product_history(
        source: str,
        identity_key: str,
        limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
        offset: int = Query(0, ge=0),
    ) -> dict:
        items = get_product_history(
            session_factory,
            source=source,
            identity_key=identity_key,
            limit=limit,
            offset=offset,
        )
        return {
            "source": source,
            "identity_key": identity_key,
            "items": items,
            "limit": limit,
            "offset": offset,
            "returned": len(items),
        }

    @app.get("/runs")
    def runs(
        source: str | None = None,
        status: str | None = None,
        limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
        offset: int = Query(0, ge=0),
    ) -> dict:
        items = list_runs(
            session_factory,
            source=source,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "items": items,
            "limit": limit,
            "offset": offset,
            "returned": len(items),
        }

    return app
