from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from src.acquisition.models import RawEvidence
from src.catalogs.models import (
    CatalogAcquisition,
    CatalogChunkResult,
    CatalogChunkStatus,
    CatalogRunStatus,
)
from src.products.models import ProductObservation, ProductPresenceStatus, StateDecision
from src.products import validation as product_validation
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


SOURCE = "m9_test_source"
SCOPE = "m9-postgres-coverage-test"
BASE = "https://m9.test/catalog"
EXTRACTOR_VERSION = "m9-pg-v1"
A = "m9-pg-a"
B = "m9-pg-b"
C = "m9-pg-c"
TEST_RECORD_IDS = (A, B, C)
T0 = datetime(2026, 9, 5, 4, 0, tzinfo=timezone.utc)


def _evidence(evidence_id: str, page: int, at: datetime, *, status: int = 200) -> RawEvidence:
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=f"{BASE}?page={page}",
        fetched_at=at,
        status_code=status,
        content_type="application/json",
        body=f'{{"page":{page},"run":"{evidence_id}"}}',
    )


def _observation(evidence: RawEvidence, record_id: str) -> ProductObservation:
    return ProductObservation(
        evidence_id=evidence.id,
        extractor_version=EXTRACTOR_VERSION,
        source=SOURCE,
        source_url=evidence.source_url,
        observed_at=evidence.fetched_at,
        title_raw=f"M9 {record_id}",
        price_raw="10.00",
        availability_raw="Out of stock",
        category_raw="M9",
        currency_raw="USD",
        source_record_id_raw=record_id,
    )


def _success(sequence: int, evidence: RawEvidence, ids: tuple[str, ...], next_ref: str | None):
    return CatalogChunkResult(
        sequence=sequence,
        requested_ref=evidence.source_url,
        attempted_at=evidence.fetched_at,
        status=CatalogChunkStatus.SUCCESS,
        evidence=evidence,
        observations=tuple(_observation(evidence, item) for item in ids),
        next_ref=next_ref,
    )


def _clean(factory) -> None:
    with factory() as session:
        with session.begin():
            product_ids = list(
                session.scalars(
                    select(ProductRow.id).where(
                        ProductRow.source == SOURCE,
                        ProductRow.source_record_id.in_(TEST_RECORD_IDS),
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
                    ProductObservationRow.source_record_id.in_(TEST_RECORD_IDS),
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
                    delete(CatalogRunChunkRow).where(CatalogRunChunkRow.catalog_run_id.in_(run_ids))
                )
                session.execute(delete(CatalogRunRow).where(CatalogRunRow.id.in_(run_ids)))
            session.execute(delete(RawEvidenceRow).where(RawEvidenceRow.source_url.like(f"{BASE}%")))


@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1" or not os.getenv("DATABASE_URL"),
    reason="set RUN_POSTGRES=1 and DATABASE_URL",
)
def test_m9_postgres_disappearance_requires_persisted_terminal_coverage_proof(monkeypatch) -> None:
    engine = create_database_engine(os.environ["DATABASE_URL"])
    factory = create_session_factory(engine)
    monkeypatch.setitem(product_validation.SOURCE_HOSTS, SOURCE, "m9.test")
    try:
        _clean(factory)

        i1 = _evidence("m9-pg-init-1", 1, T0)
        i2 = _evidence("m9-pg-init-2", 2, T0 + timedelta(seconds=1))
        initial = CatalogAcquisition(
            run_key="m9-pg-initial",
            source=SOURCE,
            scope_key=SCOPE,
            start_ref=i1.source_url,
            chunks=(
                _success(0, i1, (A, B), i2.source_url),
                _success(1, i2, (C,), None),
            ),
        )
        initial_runs = persist_catalog_acquisition(
            factory,
            initial,
            changed_at=T0 + timedelta(seconds=2),
        )
        assert [run.transition.decision for run in initial_runs] == [
            StateDecision.CREATE,
            StateDecision.CREATE,
            StateDecision.CREATE,
        ]

        with factory() as session:
            initial_c = session.scalar(
                select(ProductRow).where(
                    ProductRow.source == SOURCE,
                    ProductRow.source_record_id == C,
                )
            )
            assert initial_c is not None
            assert initial_c.presence_status == ProductPresenceStatus.ACTIVE.value

        p1 = _evidence("m9-pg-partial-1", 1, T0 + timedelta(minutes=5))
        p2 = _evidence(
            "m9-pg-partial-2",
            2,
            T0 + timedelta(minutes=5, seconds=1),
            status=503,
        )
        partial = CatalogAcquisition(
            run_key="m9-pg-partial",
            source=SOURCE,
            scope_key=SCOPE,
            start_ref=p1.source_url,
            chunks=(
                _success(0, p1, (A, B), p2.source_url),
                CatalogChunkResult(
                    sequence=1,
                    requested_ref=p2.source_url,
                    attempted_at=p2.fetched_at,
                    status=CatalogChunkStatus.HTTP_ERROR,
                    evidence=p2,
                    error_code="HTTP_503",
                ),
            ),
        )
        assert partial.coverage_status == CatalogRunStatus.INCOMPLETE
        persist_catalog_acquisition(
            factory,
            partial,
            changed_at=T0 + timedelta(minutes=5, seconds=2),
        )

        with factory() as session:
            c = session.scalar(
                select(ProductRow).where(
                    ProductRow.source == SOURCE,
                    ProductRow.source_record_id == C,
                )
            )
            assert c is not None
            assert c.presence_status == ProductPresenceStatus.ACTIVE.value
            partial_run = session.scalar(
                select(CatalogRunRow).where(CatalogRunRow.run_key == "m9-pg-partial")
            )
            assert partial_run is not None
            assert partial_run.status == CatalogRunStatus.INCOMPLETE.value
            chunks = list(
                session.scalars(
                    select(CatalogRunChunkRow)
                    .where(CatalogRunChunkRow.catalog_run_id == partial_run.id)
                    .order_by(CatalogRunChunkRow.sequence)
                )
            )
            assert [chunk.status for chunk in chunks] == ["SUCCESS", "HTTP_ERROR"]

        f1 = _evidence("m9-pg-final-1", 1, T0 + timedelta(minutes=10))
        f2 = _evidence("m9-pg-final-2", 2, T0 + timedelta(minutes=10, seconds=1))
        final = CatalogAcquisition(
            run_key="m9-pg-final",
            source=SOURCE,
            scope_key=SCOPE,
            start_ref=f1.source_url,
            chunks=(
                _success(0, f1, (A,), f2.source_url),
                _success(1, f2, (B,), None),
            ),
        )
        assert final.coverage_status == CatalogRunStatus.COMPLETE
        persist_catalog_acquisition(
            factory,
            final,
            changed_at=T0 + timedelta(minutes=10, seconds=2),
        )

        with factory() as session:
            c = session.scalar(
                select(ProductRow).where(
                    ProductRow.source == SOURCE,
                    ProductRow.source_record_id == C,
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
            proof_run = session.get(CatalogRunRow, history[-1].catalog_run_id)
            assert proof_run is not None
            assert proof_run.status == CatalogRunStatus.COMPLETE.value
            proof_chunks = list(
                session.scalars(
                    select(CatalogRunChunkRow)
                    .where(CatalogRunChunkRow.catalog_run_id == proof_run.id)
                    .order_by(CatalogRunChunkRow.sequence)
                )
            )
            assert len(proof_chunks) == 2
            assert all(chunk.status == CatalogChunkStatus.SUCCESS.value for chunk in proof_chunks)
            assert proof_chunks[0].next_ref == f2.source_url
            assert proof_chunks[1].next_ref is None
    finally:
        _clean(factory)
        engine.dispose()
