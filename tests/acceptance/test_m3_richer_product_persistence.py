from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.acquisition.models import RawEvidence
from src.products.models import StateDecision
from src.storage.models import Base, ProductHistoryRow, ProductObservationRow, ProductRow
from src.storage.service import persist_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scraping_sandbox_product.html"
URL = "https://scrapingsandbox.com/product/1"
T0 = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _evidence() -> RawEvidence:
    return RawEvidence.capture(
        evidence_id="m3-persistence",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html",
        body=FIXTURE.read_text(encoding="utf-8"),
    )


def test_m3_persists_richer_semantics_and_history_snapshot() -> None:
    session_factory = _factory()
    run = persist_product_evidence(session_factory, _evidence(), changed_at=T0)
    assert run.transition.decision == StateDecision.CREATE

    with session_factory() as session:
        product = session.scalar(select(ProductRow))
        observation = session.scalar(select(ProductObservationRow))
        history = session.scalar(select(ProductHistoryRow))

        assert product is not None
        assert observation is not None
        assert history is not None
        assert product.compare_at_price == Decimal("206.69")
        assert product.sku == "SKU-HEA-0001"
        assert product.categories == ["Health"]
        assert len(product.variants) == 4
        assert observation.compare_at_price_raw == "206.69"
        assert len(observation.variants_raw) == 4
        assert history.new_state["compare_at_price"] == "206.69"
        assert len(history.new_state["variants"]) == 4
