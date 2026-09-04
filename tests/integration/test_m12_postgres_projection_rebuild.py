from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from src.acquisition.models import RawEvidence
from src.catalogs.acquisition import single_payload_catalog_acquisition
from src.extractors.registry import ExtractorRuntime, RUNTIME_REGISTRY
from src.products import validation as product_validation
from src.products.models import ProductObservation, ProductPresenceStatus
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import (
    CatalogRunChunkRow,
    CatalogRunRow,
    ProductHistoryRow,
    ProductObservationRow,
    ProductRow,
    RawEvidenceRow,
)
from src.storage.rebuild import rebuild_source_projection_in_place
from src.storage.replay import replay_source_projection
from src.storage.service import persist_catalog_acquisition


SOURCE = "m12_pg_test_source"
VERSION = "m12-pg-v1"
SCOPE = "m12-pg-full-catalog"
URL = "https://m12-pg.test/catalog"
T0 = datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)


def _extract(evidence: RawEvidence) -> tuple[ProductObservation, ...]:
    payload = json.loads(evidence.body)
    observations: list[ProductObservation] = []
    for item in payload["products"]:
        observations.append(
            ProductObservation(
                evidence_id=evidence.id,
                extractor_version=VERSION,
                source=SOURCE,
                source_url=evidence.source_url,
                observed_at=evidence.fetched_at,
                title_raw=item["title"],
                price_raw=str(item["price"]),
                availability_raw="Out of stock",
                category_raw="M12",
                currency_raw="USD",
                source_record_id_raw=item["id"],
            )
        )
    return tuple(observations)


def _run(
    *,
    run_key: str,
    at: datetime,
    a_price: str = "10.00",
    include_c: bool = True,
):
    products = [
        {"id": "m12-pg-a", "title": "M12 PG A", "price": a_price},
        {"id": "m12-pg-b", "title": "M12 PG B", "price": "20.00"},
    ]
    if include_c:
        products.append({"id": "m12-pg-c", "title": "M12 PG C", "price": "30.00"})
    evidence = RawEvidence.capture(
        evidence_id=f"{run_key}-evidence",
        source_url=URL,
        fetched_at=at,
        status_code=200,
        content_type="application/json",
        body=json.dumps({"products": products}),
    )
    return single_payload_catalog_acquisition(
        source=SOURCE,
        scope_key=SCOPE,
        evidence=evidence,
        observations=_extract(evidence),
        run_key=run_key,
    )


def _seed(factory) -> None:
    persist_catalog_acquisition(
        factory,
        _run(run_key="m12-pg-initial", at=T0),
        changed_at=T0 + timedelta(seconds=1),
    )
    persist_catalog_acquisition(
        factory,
        _run(
            run_key="m12-pg-update",
            at=T0 + timedelta(minutes=5),
            a_price="11.00",
        ),
        changed_at=T0 + timedelta(minutes=5, seconds=1),
    )
    persist_catalog_acquisition(
        factory,
        _run(
            run_key="m12-pg-disappear",
            at=T0 + timedelta(minutes=10),
            a_price="11.00",
            include_c=False,
        ),
        changed_at=T0 + timedelta(minutes=10, seconds=1),
    )
    persist_catalog_acquisition(
        factory,
        _run(
            run_key="m12-pg-repeat-absence",
            at=T0 + timedelta(minutes=15),
            a_price="11.00",
            include_c=False,
        ),
        changed_at=T0 + timedelta(minutes=15, seconds=1),
    )


def _clean(factory) -> None:
    with factory() as session:
        with session.begin():
            session.execute(delete(ProductHistoryRow).where(ProductHistoryRow.source == SOURCE))
            session.execute(delete(ProductRow).where(ProductRow.source == SOURCE))
            session.execute(delete(ProductObservationRow).where(ProductObservationRow.source == SOURCE))

            run_ids = list(
                session.scalars(
                    select(CatalogRunRow.id).where(CatalogRunRow.source == SOURCE)
                )
            )
            if run_ids:
                session.execute(
                    delete(CatalogRunChunkRow).where(
                        CatalogRunChunkRow.catalog_run_id.in_(run_ids)
                    )
                )
                session.execute(delete(CatalogRunRow).where(CatalogRunRow.id.in_(run_ids)))
            session.execute(
                delete(RawEvidenceRow).where(RawEvidenceRow.id.like("m12-pg-%-evidence"))
            )


@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1" or not os.getenv("DATABASE_URL"),
    reason="set RUN_POSTGRES=1 and DATABASE_URL",
)
def test_m12_postgres_delete_recreate_projection_is_recoverable_and_rollback_safe(
    monkeypatch,
) -> None:
    engine = create_database_engine(os.environ["DATABASE_URL"])
    factory = create_session_factory(engine)
    monkeypatch.setitem(product_validation.SOURCE_HOSTS, SOURCE, "m12-pg.test")
    monkeypatch.setitem(
        RUNTIME_REGISTRY,
        (SOURCE, VERSION),
        ExtractorRuntime(
            source=SOURCE,
            version=VERSION,
            implementation="tests.integration.test_m12_postgres_projection_rebuild:_extract",
            extract=_extract,
        ),
    )

    try:
        _clean(factory)
        _seed(factory)

        with factory() as session:
            before_rows = list(
                session.scalars(
                    select(ProductRow)
                    .where(ProductRow.source == SOURCE)
                    .order_by(ProductRow.identity_key)
                )
            )
            before_ids = {row.identity_key: row.id for row in before_rows}
            history_ids = tuple(
                session.scalars(
                    select(ProductHistoryRow.id)
                    .where(ProductHistoryRow.source == SOURCE)
                    .order_by(ProductHistoryRow.id)
                )
            )
            assert len(before_rows) == 3
            assert len(history_ids) == 5

        with factory() as session:
            transaction = session.begin()
            try:
                report = rebuild_source_projection_in_place(session, source=SOURCE)
                assert report.is_consistent
                assert report.issues == ()
                assert len(report.products) == 3
                # Healthy verification reuses old surrogate ids, so PostgreSQL
                # sequences do not advance merely because the proof is rolled back.
                assert {
                    item.identity_key: item.new_product_id for item in report.products
                } == before_ids

                c = session.scalar(
                    select(ProductRow).where(
                        ProductRow.source == SOURCE,
                        ProductRow.source_record_id == "m12-pg-c",
                    )
                )
                assert c is not None
                assert c.presence_status == ProductPresenceStatus.DISAPPEARED.value
                assert c.presence_observed_at == T0 + timedelta(minutes=15)

                linked = list(
                    session.scalars(
                        select(ProductHistoryRow)
                        .where(ProductHistoryRow.source == SOURCE)
                        .order_by(ProductHistoryRow.id)
                    )
                )
                assert tuple(item.id for item in linked) == history_ids
                assert all(item.product_id is not None for item in linked)

                replay = replay_source_projection(session, source=SOURCE)
                assert replay.is_consistent
                assert replay.issues == ()
            finally:
                transaction.rollback()

        with factory() as session:
            after_ids = {
                row.identity_key: row.id
                for row in session.scalars(
                    select(ProductRow)
                    .where(ProductRow.source == SOURCE)
                    .order_by(ProductRow.identity_key)
                )
            }
            after_history = tuple(
                session.scalars(
                    select(ProductHistoryRow.id)
                    .where(ProductHistoryRow.source == SOURCE)
                    .order_by(ProductHistoryRow.id)
                )
            )
            assert after_ids == before_ids
            assert after_history == history_ids
    finally:
        _clean(factory)
        engine.dispose()
