import os

import pytest
from sqlalchemy import delete, select

from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import (
    ProductHistoryRow,
    ProductObservationRow,
    ProductRow,
    RawEvidenceRow,
)
from src.storage.service import persist_product_url


URL = "https://scrapeme.live/shop/Charizard/"


@pytest.mark.live
@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_LIVE") != "1" or os.getenv("RUN_POSTGRES") != "1",
    reason="set RUN_LIVE=1 and RUN_POSTGRES=1",
)
def test_live_scrapeme_is_traceable_from_source_to_postgres() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)

    try:
        with session_factory() as session:
            with session.begin():
                product = session.scalar(
                    select(ProductRow).where(
                        ProductRow.source == "scrapeme_live",
                        ProductRow.canonical_product_url == URL,
                    )
                )
                if product is not None:
                    session.execute(
                        delete(ProductHistoryRow).where(
                            ProductHistoryRow.product_id == product.id
                        )
                    )
                    session.delete(product)

        result = persist_product_url(session_factory, URL)
        assert result.product_id is not None
        assert result.observation.source == "scrapeme_live"
        assert result.transition.current_state is not None

        with session_factory() as session:
            product = session.get(ProductRow, result.product_id)
            observation = session.get(ProductObservationRow, result.observation_id)
            evidence = session.get(RawEvidenceRow, result.evidence.id)
            history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.product_id == result.product_id)
                    .order_by(ProductHistoryRow.id)
                )
            )

            assert product is not None
            assert observation is not None
            assert evidence is not None
            assert len(history) == 1
            assert product.source == "scrapeme_live"
            assert product.accepted_observation_id == observation.id
            assert observation.evidence_id == evidence.id
            assert history[0].observation_id == observation.id
            assert history[0].new_state["title"] == product.title
            assert history[0].new_state["price"] == str(product.price)
            assert evidence.body
    finally:
        engine.dispose()
