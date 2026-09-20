from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import (
    CatalogRunChunkRow,
    CatalogRunRow,
    ProductHistoryRow,
    ProductObservationRow,
    ProductRow,
    RawEvidenceRow,
)
from src.storage.service import persist_catalog_acquisition
from src.web_scraping_dev.acquisition import HttpPageSnapshot, acquire_web_scraping_dev_catalog

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1" or not os.getenv("DATABASE_URL"),
    reason="set RUN_POSTGRES=1 and DATABASE_URL",
)


def test_m19_postgres_real_source_uses_existing_persistence_path_without_absence_reconciliation():
    token = uuid.uuid4().hex[:8]
    first_id = int("9" + str(int(token[:6], 16))[:6])
    second_id = first_id + 1
    t0 = datetime.now(timezone.utc)
    cat_url = "https://web-scraping.dev/products?page=1"
    p1 = f"https://web-scraping.dev/product/{first_id}"
    p2 = f"https://web-scraping.dev/product/{second_id}"
    cat_body = f'<a href="/product/{first_id}">one</a><a href="/product/{second_id}">two</a>'
    detail_body = '<h3 class="product-title">M19 PG Fixture</h3><span class="product-price">$11.00</span><span class="product-price-full">$13.00</span><span class="stock-status" data-available="true"></span>'

    def snapshot(ref: str, body: str) -> HttpPageSnapshot:
        return HttpPageSnapshot(ref, t0, ref, 200, "text/html", body)

    fixture = {
        cat_url: snapshot(cat_url, cat_body),
        p1: snapshot(p1, detail_body),
        p2: snapshot(p2, detail_body),
    }
    run_key = f"m19-pg-{token}"
    acquisition = acquire_web_scraping_dev_catalog(
        load_page=fixture.__getitem__, max_products=1, run_key=run_key
    )
    # max_products=1 deliberately makes the run INCOMPLETE. The observed product
    # is persisted, while M8/M9 absence reconciliation remains disabled.
    factory = create_session_factory(create_database_engine(os.environ["DATABASE_URL"]))
    try:
        runs = persist_catalog_acquisition(factory, acquisition, changed_at=t0)
        assert len(runs) == 1

        with factory() as session:
            row = session.scalar(
                select(ProductRow).where(
                    ProductRow.source == "web_scraping_dev",
                    ProductRow.source_record_id == str(first_id),
                )
            )
            assert row is not None
            assert row.title == "M19 PG Fixture"
            assert row.presence_status == "ACTIVE"
            history = list(
                session.scalars(
                    select(ProductHistoryRow).where(
                        ProductHistoryRow.source == "web_scraping_dev",
                        ProductHistoryRow.identity_key == f"id:{first_id}",
                    )
                )
            )
            assert [item.decision for item in history] == ["CREATE"]
    finally:
        with factory() as session:
            with session.begin():
                run = session.scalar(select(CatalogRunRow).where(CatalogRunRow.run_key == run_key))
                session.execute(
                    delete(ProductHistoryRow).where(
                        ProductHistoryRow.source == "web_scraping_dev",
                        ProductHistoryRow.identity_key == f"id:{first_id}",
                    )
                )
                session.execute(
                    delete(ProductRow).where(
                        ProductRow.source == "web_scraping_dev",
                        ProductRow.source_record_id == str(first_id),
                    )
                )
                session.execute(
                    delete(ProductObservationRow).where(
                        ProductObservationRow.source == "web_scraping_dev",
                        ProductObservationRow.source_record_id == str(first_id),
                    )
                )
                if run is not None:
                    session.execute(delete(CatalogRunChunkRow).where(CatalogRunChunkRow.catalog_run_id == run.id))
                    session.execute(delete(CatalogRunRow).where(CatalogRunRow.id == run.id))
                evidence_ids = [item.id for item in acquisition.evidence]
                if evidence_ids:
                    session.execute(delete(RawEvidenceRow).where(RawEvidenceRow.id.in_(evidence_ids)))
