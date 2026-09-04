from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from src.acquisition.models import RawEvidence
from src.catalogs.models import CatalogAcquisition, CatalogChunkResult, CatalogChunkStatus
from src.products import validation as product_validation
from src.products.models import ProductObservation, ProductPresenceStatus, StateDecision
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import (
    CatalogRunChunkRow,
    CatalogRunRow,
    ProductHistoryRow,
    ProductObservationRow,
    ProductRow,
    RawEvidenceRow,
)
from src.storage.replay import replay_source_projection
from src.storage.service import persist_catalog_acquisition


SOURCE = "m10_pg_test_source"
SCOPE = "m10-pg-replay-scope"
BASE = "https://m10-pg.test/catalog"
EXTRACTOR_VERSION = "m10-pg-v1"
A = "m10-pg-a"
B = "m10-pg-b"
C = "m10-pg-c"
RECORD_IDS = (A, B, C)
RUN_KEYS = (
    "m10-pg-initial",
    "m10-pg-unchanged",
    "m10-pg-disappear",
    "m10-pg-repeat-absence",
)
T0 = datetime(2026, 9, 5, 7, 0, tzinfo=timezone.utc)


def _evidence(evidence_id: str, at: datetime) -> RawEvidence:
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=BASE,
        fetched_at=at,
        status_code=200,
        content_type="application/json",
        body=f'{{"run":"{evidence_id}"}}',
    )


def _observation(evidence: RawEvidence, record_id: str) -> ProductObservation:
    return ProductObservation(
        evidence_id=evidence.id,
        extractor_version=EXTRACTOR_VERSION,
        source=SOURCE,
        source_url=evidence.source_url,
        observed_at=evidence.fetched_at,
        title_raw=f"M10 PG {record_id}",
        price_raw="10.00",
        availability_raw="Out of stock",
        category_raw="M10",
        currency_raw="USD",
        source_record_id_raw=record_id,
    )


def _complete_run(run_key: str, at: datetime, ids: tuple[str, ...]) -> CatalogAcquisition:
    evidence = _evidence(f"{run_key}-evidence", at)
    return CatalogAcquisition(
        run_key=run_key,
        source=SOURCE,
        scope_key=SCOPE,
        start_ref=BASE,
        chunks=(
            CatalogChunkResult(
                sequence=0,
                requested_ref=BASE,
                attempted_at=at,
                status=CatalogChunkStatus.SUCCESS,
                evidence=evidence,
                observations=tuple(_observation(evidence, item) for item in ids),
                next_ref=None,
            ),
        ),
    )


def _clean(factory) -> None:
    with factory() as session:
        with session.begin():
            product_ids = list(
                session.scalars(
                    select(ProductRow.id).where(
                        ProductRow.source == SOURCE,
                        ProductRow.source_record_id.in_(RECORD_IDS),
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
                    ProductObservationRow.source == SOURCE,
                    ProductObservationRow.extractor_version == EXTRACTOR_VERSION,
                )
            )

            run_ids = list(
                session.scalars(
                    select(CatalogRunRow.id).where(
                        CatalogRunRow.source == SOURCE,
                        CatalogRunRow.scope_key == SCOPE,
                    )
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
                delete(RawEvidenceRow).where(
                    RawEvidenceRow.id.like("m10-pg-%-evidence")
                )
            )


def _seed(factory) -> None:
    persist_catalog_acquisition(
        factory,
        _complete_run("m10-pg-initial", T0, (A, B, C)),
        changed_at=T0 + timedelta(seconds=1),
    )
    persist_catalog_acquisition(
        factory,
        _complete_run("m10-pg-unchanged", T0 + timedelta(minutes=5), (A, B, C)),
        changed_at=T0 + timedelta(minutes=5, seconds=1),
    )
    persist_catalog_acquisition(
        factory,
        _complete_run("m10-pg-disappear", T0 + timedelta(minutes=10), (A, B)),
        changed_at=T0 + timedelta(minutes=10, seconds=1),
    )
    persist_catalog_acquisition(
        factory,
        _complete_run("m10-pg-repeat-absence", T0 + timedelta(minutes=15), (A, B)),
        changed_at=T0 + timedelta(minutes=15, seconds=1),
    )


@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1" or not os.getenv("DATABASE_URL"),
    reason="set RUN_POSTGRES=1 and DATABASE_URL",
)
def test_m10_postgres_replay_matches_projection_and_detects_drift(monkeypatch) -> None:
    engine = create_database_engine(os.environ["DATABASE_URL"])
    factory = create_session_factory(engine)
    monkeypatch.setitem(product_validation.SOURCE_HOSTS, SOURCE, "m10-pg.test")

    try:
        _clean(factory)
        _seed(factory)

        with factory() as session:
            report = replay_source_projection(session, source=SOURCE)
            assert report.is_consistent
            assert len(report.products) == 3

            c_row = session.scalar(
                select(ProductRow).where(
                    ProductRow.source == SOURCE,
                    ProductRow.source_record_id == C,
                )
            )
            assert c_row is not None
            assert c_row.presence_status == ProductPresenceStatus.DISAPPEARED.value
            assert c_row.presence_observed_at == T0 + timedelta(minutes=15)
            c_history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.product_id == c_row.id)
                    .order_by(ProductHistoryRow.id)
                )
            )
            assert [item.decision for item in c_history] == [
                StateDecision.CREATE.value,
                StateDecision.DISAPPEARED.value,
            ]

        # Drift proof without leaving pollution: corrupt inside one transaction,
        # replay against that snapshot, then roll it back.
        with factory() as session:
            transaction = session.begin()
            try:
                a_row = session.scalar(
                    select(ProductRow).where(
                        ProductRow.source == SOURCE,
                        ProductRow.source_record_id == A,
                    )
                )
                assert a_row is not None
                a_row.price = Decimal("999.00")
                session.flush()
                drift = replay_source_projection(session, source=SOURCE)
                assert not drift.is_consistent
                assert "CURRENT_PROJECTION_MISMATCH" in {
                    item.code for item in drift.issues
                }
            finally:
                transaction.rollback()
    finally:
        _clean(factory)
        engine.dispose()
