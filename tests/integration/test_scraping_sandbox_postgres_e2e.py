import os
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import ProductHistoryRow, ProductObservationRow, ProductRow
from src.storage.service import persist_product_url


URL = "https://scrapingsandbox.com/product/1"


@pytest.mark.live
@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_LIVE") != "1" or os.getenv("RUN_POSTGRES") != "1",
    reason="set RUN_LIVE=1 and RUN_POSTGRES=1",
)
def test_m3_live_richer_product_semantics_reach_postgres_and_history() -> None:
    engine = create_database_engine(os.environ["DATABASE_URL"])
    session_factory = create_session_factory(engine)

    try:
        with session_factory() as session:
            with session.begin():
                product = session.scalar(
                    select(ProductRow).where(
                        ProductRow.source == "scraping_sandbox",
                        ProductRow.source_record_id == "1",
                    )
                )
                if product is not None:
                    session.execute(
                        delete(ProductHistoryRow).where(
                            ProductHistoryRow.product_id == product.id
                        )
                    )
                    session.delete(product)
                session.execute(
                    delete(ProductObservationRow).where(
                        ProductObservationRow.source == "scraping_sandbox"
                    )
                )

        result = persist_product_url(session_factory, URL)
        assert result.product_id is not None

        with session_factory() as session:
            product = session.get(ProductRow, result.product_id)
            history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.product_id == result.product_id)
                    .order_by(ProductHistoryRow.id)
                )
            )
            assert product is not None
            assert product.compare_at_price == Decimal("206.69")
            assert product.sku == "SKU-HEA-0001"
            assert product.categories == ["Health"]
            assert len(product.variants) == 4
            assert len(history) == 1
            assert history[0].new_state["variants"][2]["availability"] == "OUT_OF_STOCK"
    finally:
        engine.dispose()
