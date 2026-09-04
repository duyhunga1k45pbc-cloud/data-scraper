import os

import pytest
from sqlalchemy import delete, func, select

from src.scrapify_js.service import persist_catalog
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import (
    CatalogRunChunkRow,
    CatalogRunRow,
    ProductHistoryRow,
    ProductObservationRow,
    ProductRow,
)


@pytest.mark.live
@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_LIVE") != "1" or os.getenv("RUN_POSTGRES") != "1",
    reason="set RUN_LIVE=1 and RUN_POSTGRES=1",
)
def test_m2_live_json_catalog_reaches_shared_postgres_state_and_history() -> None:
    engine = create_database_engine(os.environ["DATABASE_URL"])
    session_factory = create_session_factory(engine)

    try:
        with session_factory() as session:
            with session.begin():
                product_ids = list(
                    session.scalars(
                        select(ProductRow.id).where(ProductRow.source == "scrapify_js")
                    )
                )
                if product_ids:
                    session.execute(
                        delete(ProductHistoryRow).where(
                            ProductHistoryRow.product_id.in_(product_ids)
                        )
                    )
                    session.execute(
                        delete(ProductRow).where(ProductRow.id.in_(product_ids))
                    )
                session.execute(
                    delete(ProductObservationRow).where(
                        ProductObservationRow.source == "scrapify_js"
                    )
                )

        results = persist_catalog(session_factory)
        assert len(results) >= 10
        assert all(run.product_id is not None for run in results)

        with session_factory() as session:
            catalog_run = session.scalar(
                select(CatalogRunRow).where(
                    CatalogRunRow.evidence_id == results[0].evidence.id,
                    CatalogRunRow.source == "scrapify_js",
                )
            )
            assert catalog_run is not None
            assert catalog_run.status == "COMPLETE"
            assert catalog_run.record_count == len(results)
            coverage_chunks = list(
                session.scalars(
                    select(CatalogRunChunkRow)
                    .where(CatalogRunChunkRow.catalog_run_id == catalog_run.id)
                    .order_by(CatalogRunChunkRow.sequence)
                )
            )
            assert len(coverage_chunks) == 1
            assert coverage_chunks[0].status == "SUCCESS"
            assert coverage_chunks[0].evidence_id == results[0].evidence.id
            assert coverage_chunks[0].next_ref is None
            product_count = session.scalar(
                select(func.count()).select_from(ProductRow).where(
                    ProductRow.source == "scrapify_js"
                )
            )
            observation_count = session.scalar(
                select(func.count()).select_from(ProductObservationRow).where(
                    ProductObservationRow.source == "scrapify_js"
                )
            )
            history_count = session.scalar(
                select(func.count())
                .select_from(ProductHistoryRow)
                .join(ProductRow, ProductHistoryRow.product_id == ProductRow.id)
                .where(ProductRow.source == "scrapify_js")
            )

            assert product_count == len(results)
            assert observation_count == len(results)
            assert history_count == len(results)

            first = session.scalar(
                select(ProductRow)
                .where(ProductRow.source == "scrapify_js")
                .order_by(ProductRow.source_record_id)
            )
            assert first is not None
            assert first.source_record_id
            assert first.identity_key == f"id:{first.source_record_id}"
            assert first.currency == "USD"
    finally:
        engine.dispose()
