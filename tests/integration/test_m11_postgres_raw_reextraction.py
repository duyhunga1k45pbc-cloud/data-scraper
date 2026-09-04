from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from src.acquisition.models import RawEvidence
from src.products.normalization import canonicalize_product_url
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import (
    ProductHistoryRow,
    ProductObservationRow,
    ProductRow,
    RawEvidenceRow,
)
from src.storage.reextraction import verify_source_reextraction
from src.storage.service import persist_product_evidence


SOURCE = "books_to_scrape"
EVIDENCE_ID = "m11-pg-book-evidence"
URL = "https://books.toscrape.com/catalogue/m11-postgres-reextraction/index.html"
CANONICAL_URL = canonicalize_product_url(URL)
T0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parents[1] / "fixtures" / "book_product.html"


def _clean(factory) -> None:
    with factory() as session:
        with session.begin():
            product_ids = list(
                session.scalars(
                    select(ProductRow.id).where(
                        ProductRow.source == SOURCE,
                        ProductRow.canonical_product_url == CANONICAL_URL,
                    )
                )
            )
            if product_ids:
                session.execute(
                    delete(ProductHistoryRow).where(ProductHistoryRow.product_id.in_(product_ids))
                )
                session.execute(delete(ProductRow).where(ProductRow.id.in_(product_ids)))
            session.execute(
                delete(ProductObservationRow).where(
                    ProductObservationRow.evidence_id == EVIDENCE_ID
                )
            )
            session.execute(delete(RawEvidenceRow).where(RawEvidenceRow.id == EVIDENCE_ID))


@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1" or not os.getenv("DATABASE_URL"),
    reason="set RUN_POSTGRES=1 and DATABASE_URL",
)
def test_m11_postgres_reextracts_raw_evidence_with_recorded_runtime() -> None:
    engine = create_database_engine(os.environ["DATABASE_URL"])
    factory = create_session_factory(engine)
    try:
        _clean(factory)
        evidence = RawEvidence.capture(
            evidence_id=EVIDENCE_ID,
            source_url=URL,
            fetched_at=T0,
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=FIXTURE.read_text(encoding="utf-8"),
        )
        persist_product_evidence(factory, evidence, changed_at=T0)

        with factory() as session:
            report = verify_source_reextraction(
                session,
                source=SOURCE,
                evidence_ids={EVIDENCE_ID},
            )

        assert report.is_consistent
        assert report.issues == ()
        assert report.observations == 1
        assert len(report.evidence) == 1
        assert report.evidence[0].implementation == (
            "src.extractors.books_to_scrape_v1:parse_book"
        )
    finally:
        _clean(factory)
        engine.dispose()
