from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.acquisition.models import RawEvidence
from src.storage.models import (
    Base,
    ProductHistoryRow,
    ProductObservationRow,
    ProductRow,
    RawEvidenceRow,
)
from src.storage.service import persist_product_evidence


BOOK_FIXTURE = Path(__file__).parents[1] / "fixtures" / "book_product.html"
SCRAPEME_FIXTURE = Path(__file__).parents[1] / "fixtures" / "scrapeme_product.html"
BOOK_URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
SCRAPEME_URL = "https://scrapeme.live/shop/Charizard/"
T0 = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _evidence(evidence_id: str, url: str, fixture: Path) -> RawEvidence:
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=url,
        fetched_at=T0,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=fixture.read_text(),
    )


def test_m1_two_sources_share_one_product_state_and_history_model() -> None:
    session_factory = _factory()

    book = persist_product_evidence(
        session_factory,
        _evidence("m1-book", BOOK_URL, BOOK_FIXTURE),
        changed_at=T0,
    )
    ecommerce = persist_product_evidence(
        session_factory,
        _evidence("m1-scrapeme", SCRAPEME_URL, SCRAPEME_FIXTURE),
        changed_at=T0,
    )

    assert book.product_id is not None
    assert ecommerce.product_id is not None

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(RawEvidenceRow)) == 2
        assert session.scalar(select(func.count()).select_from(ProductObservationRow)) == 2
        assert session.scalar(select(func.count()).select_from(ProductRow)) == 2
        assert session.scalar(select(func.count()).select_from(ProductHistoryRow)) == 2

        sources = set(session.scalars(select(ProductRow.source)))
        assert sources == {"books_to_scrape", "scrapeme_live"}
