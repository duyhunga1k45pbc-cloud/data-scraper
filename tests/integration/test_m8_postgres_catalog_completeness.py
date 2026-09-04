from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from src.acquisition.models import RawEvidence
from src.products.models import ProductObservation, ProductPresenceStatus, StateDecision
from src.products import validation as product_validation
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import (
    CatalogRunRow,
    ProductHistoryRow,
    ProductObservationRow,
    ProductRow,
    RawEvidenceRow,
)
from src.storage.service import CatalogRunStatus, persist_catalog_observations


SOURCE = "m8_test_source"
URL = "https://m8.test/catalog.json"
T0 = datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc)


def _observation(evidence: RawEvidence, record_id: str) -> ProductObservation:
    return ProductObservation(
        evidence_id=evidence.id,
        extractor_version="m8-test-v1",
        source=SOURCE,
        source_url=evidence.source_url,
        observed_at=evidence.fetched_at,
        title_raw=f"M8 {record_id}",
        price_raw="10.00",
        availability_raw="Out of stock",
        category_raw="M8",
        currency_raw="USD",
        source_record_id_raw=record_id,
    )


def _evidence(evidence_id: str, at: datetime) -> RawEvidence:
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=URL,
        fetched_at=at,
        status_code=200,
        content_type="application/json",
        body=f'{{"run":"{evidence_id}"}}',
    )


def _persist(factory, evidence_id: str, ids: tuple[str, ...], at: datetime, *, complete: bool):
    evidence = _evidence(evidence_id, at)
    observations = tuple(_observation(evidence, record_id) for record_id in ids)
    return persist_catalog_observations(
        factory,
        evidence,
        observations,
        source=SOURCE,
        scope_key="full-catalog",
        complete=complete,
        changed_at=at,
    )


def _clean(factory) -> None:
    with factory() as session:
        with session.begin():
            product_ids = list(
                session.scalars(select(ProductRow.id).where(ProductRow.source == SOURCE))
            )
            if product_ids:
                session.execute(
                    delete(ProductHistoryRow).where(ProductHistoryRow.product_id.in_(product_ids))
                )
                session.execute(delete(ProductRow).where(ProductRow.id.in_(product_ids)))
            session.execute(delete(ProductObservationRow).where(ProductObservationRow.source == SOURCE))
            session.execute(delete(CatalogRunRow).where(CatalogRunRow.source == SOURCE))
            session.execute(delete(RawEvidenceRow).where(RawEvidenceRow.source_url == URL))


@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1" or not os.getenv("DATABASE_URL"),
    reason="set RUN_POSTGRES=1 and DATABASE_URL",
)
def test_m8_postgres_requires_complete_scope_before_disappearance(monkeypatch) -> None:
    engine = create_database_engine(os.environ["DATABASE_URL"])
    factory = create_session_factory(engine)
    monkeypatch.setitem(product_validation.SOURCE_HOSTS, SOURCE, "m8.test")

    try:
        _clean(factory)
        _persist(factory, "m8-pg-1", ("a", "b", "c"), T0, complete=True)
        _persist(
            factory,
            "m8-pg-2",
            ("a", "b"),
            T0 + timedelta(minutes=5),
            complete=False,
        )

        with factory() as session:
            c = session.scalar(
                select(ProductRow).where(
                    ProductRow.source == SOURCE,
                    ProductRow.source_record_id == "c",
                )
            )
            assert c is not None
            assert c.presence_status == ProductPresenceStatus.ACTIVE.value

        _persist(
            factory,
            "m8-pg-3",
            ("a", "b"),
            T0 + timedelta(minutes=10),
            complete=True,
        )
        with factory() as session:
            c = session.scalar(
                select(ProductRow).where(
                    ProductRow.source == SOURCE,
                    ProductRow.source_record_id == "c",
                )
            )
            assert c is not None
            assert c.presence_status == ProductPresenceStatus.DISAPPEARED.value
            history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.product_id == c.id)
                    .order_by(ProductHistoryRow.id)
                )
            )
            assert [row.decision for row in history] == [
                StateDecision.CREATE.value,
                StateDecision.DISAPPEARED.value,
            ]
            assert history[-1].observation_id is None
            assert history[-1].catalog_run_id is not None

        runs = _persist(
            factory,
            "m8-pg-4",
            ("a", "b", "c"),
            T0 + timedelta(minutes=15),
            complete=True,
        )
        c_run = next(run for run in runs if run.normalized.source_record_id == "c")
        assert c_run.transition.decision == StateDecision.REAPPEARED

        with factory() as session:
            c = session.scalar(
                select(ProductRow).where(
                    ProductRow.source == SOURCE,
                    ProductRow.source_record_id == "c",
                )
            )
            assert c is not None
            assert c.presence_status == ProductPresenceStatus.ACTIVE.value
            history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.product_id == c.id)
                    .order_by(ProductHistoryRow.id)
                )
            )
            assert [row.decision for row in history] == [
                StateDecision.CREATE.value,
                StateDecision.DISAPPEARED.value,
                StateDecision.REAPPEARED.value,
            ]
            statuses = list(
                session.scalars(
                    select(CatalogRunRow.status)
                    .where(CatalogRunRow.source == SOURCE)
                    .order_by(CatalogRunRow.id)
                )
            )
            assert statuses == [
                CatalogRunStatus.COMPLETE.value,
                CatalogRunStatus.INCOMPLETE.value,
                CatalogRunStatus.COMPLETE.value,
                CatalogRunStatus.COMPLETE.value,
            ]
    finally:
        _clean(factory)
        engine.dispose()
