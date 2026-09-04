from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.acquisition.models import RawEvidence
from src.catalogs.models import (
    CatalogAcquisition,
    CatalogChunkResult,
    CatalogChunkStatus,
    CatalogRunStatus,
)
from src.products.models import ProductObservation, ProductPresenceStatus, StateDecision
from src.storage.models import (
    Base,
    CatalogRunChunkRow,
    CatalogRunRow,
    ProductHistoryRow,
    ProductRow,
)
from src.storage.service import persist_catalog_acquisition


SOURCE = "scrapify_js"
SCOPE = "m9-paginated-scope"
T0 = datetime(2026, 9, 5, 3, 0, tzinfo=timezone.utc)


def _evidence(evidence_id: str, ref: str, at: datetime, *, status: int = 200) -> RawEvidence:
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=ref,
        fetched_at=at,
        status_code=status,
        content_type="application/json",
        body=f'{{"evidence":"{evidence_id}"}}',
    )


def _observation(evidence: RawEvidence, record_id: str) -> ProductObservation:
    return ProductObservation(
        evidence_id=evidence.id,
        extractor_version="m9-test-v1",
        source=SOURCE,
        source_url=evidence.source_url,
        observed_at=evidence.fetched_at,
        title_raw=f"M9 {record_id}",
        price_raw="10.00",
        availability_raw="true",
        category_raw="M9",
        currency_raw="USD",
        source_record_id_raw=record_id,
    )


def _success_chunk(
    sequence: int,
    evidence: RawEvidence,
    ids: tuple[str, ...],
    next_ref: str | None,
) -> CatalogChunkResult:
    return CatalogChunkResult(
        sequence=sequence,
        requested_ref=evidence.source_url,
        attempted_at=evidence.fetched_at,
        status=CatalogChunkStatus.SUCCESS,
        evidence=evidence,
        observations=tuple(_observation(evidence, record_id) for record_id in ids),
        next_ref=next_ref,
    )


def _factory(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'm9.db'}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_m9_incomplete_coverage_cannot_disappear_but_proven_terminal_run_can(tmp_path) -> None:
    engine, factory = _factory(tmp_path)
    try:
        p1 = _evidence("m9-init-1", "https://scrapifydatalabs.com/catalog?page=1", T0)
        p2 = _evidence(
            "m9-init-2",
            "https://scrapifydatalabs.com/catalog?page=2",
            T0 + timedelta(seconds=1),
        )
        initial = CatalogAcquisition(
            run_key="m9-initial-complete",
            source=SOURCE,
            scope_key=SCOPE,
            start_ref=p1.source_url,
            chunks=(
                _success_chunk(0, p1, ("a", "b"), p2.source_url),
                _success_chunk(1, p2, ("c",), None),
            ),
        )
        assert initial.coverage_status == CatalogRunStatus.COMPLETE
        persist_catalog_acquisition(factory, initial, changed_at=T0 + timedelta(seconds=2))

        partial_page = _evidence(
            "m9-partial-1",
            "https://scrapifydatalabs.com/catalog?page=1",
            T0 + timedelta(minutes=5),
        )
        failed_page = _evidence(
            "m9-partial-2",
            "https://scrapifydatalabs.com/catalog?page=2",
            T0 + timedelta(minutes=5, seconds=1),
            status=503,
        )
        partial = CatalogAcquisition(
            run_key="m9-incomplete",
            source=SOURCE,
            scope_key=SCOPE,
            start_ref=partial_page.source_url,
            chunks=(
                _success_chunk(0, partial_page, ("a", "b"), failed_page.source_url),
                CatalogChunkResult(
                    sequence=1,
                    requested_ref=failed_page.source_url,
                    attempted_at=failed_page.fetched_at,
                    status=CatalogChunkStatus.HTTP_ERROR,
                    evidence=failed_page,
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
                select(ProductRow).where(ProductRow.source_record_id == "c")
            )
            assert c is not None
            assert c.presence_status == ProductPresenceStatus.ACTIVE.value
            run = session.scalar(
                select(CatalogRunRow).where(CatalogRunRow.run_key == "m9-incomplete")
            )
            assert run is not None
            assert run.status == CatalogRunStatus.INCOMPLETE.value
            chunks = list(
                session.scalars(
                    select(CatalogRunChunkRow)
                    .where(CatalogRunChunkRow.catalog_run_id == run.id)
                    .order_by(CatalogRunChunkRow.sequence)
                )
            )
            assert [item.status for item in chunks] == [
                CatalogChunkStatus.SUCCESS.value,
                CatalogChunkStatus.HTTP_ERROR.value,
            ]
            assert chunks[0].evidence_id == partial_page.id
            assert chunks[1].evidence_id == failed_page.id

        final_p1 = _evidence(
            "m9-final-1",
            "https://scrapifydatalabs.com/catalog?page=1",
            T0 + timedelta(minutes=10),
        )
        final_p2 = _evidence(
            "m9-final-2",
            "https://scrapifydatalabs.com/catalog?page=2",
            T0 + timedelta(minutes=10, seconds=1),
        )
        proven = CatalogAcquisition(
            run_key="m9-final-complete",
            source=SOURCE,
            scope_key=SCOPE,
            start_ref=final_p1.source_url,
            chunks=(
                _success_chunk(0, final_p1, ("a",), final_p2.source_url),
                _success_chunk(1, final_p2, ("b",), None),
            ),
        )
        assert proven.coverage_status == CatalogRunStatus.COMPLETE
        persist_catalog_acquisition(
            factory,
            proven,
            changed_at=T0 + timedelta(minutes=10, seconds=2),
        )

        with factory() as session:
            c = session.scalar(
                select(ProductRow).where(ProductRow.source_record_id == "c")
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
            disappearance = history[-1]
            assert disappearance.observation_id is None
            assert disappearance.catalog_run_id is not None

            proof_chunks = list(
                session.scalars(
                    select(CatalogRunChunkRow)
                    .where(CatalogRunChunkRow.catalog_run_id == disappearance.catalog_run_id)
                    .order_by(CatalogRunChunkRow.sequence)
                )
            )
            assert len(proof_chunks) == 2
            assert all(item.status == CatalogChunkStatus.SUCCESS.value for item in proof_chunks)
            assert proof_chunks[-1].next_ref is None
    finally:
        engine.dispose()


def test_m9_first_page_failure_is_persisted_without_fabricating_raw_response(tmp_path) -> None:
    engine, factory = _factory(tmp_path)
    try:
        acquisition = CatalogAcquisition(
            run_key="m9-first-page-failure",
            source=SOURCE,
            scope_key=SCOPE,
            start_ref="https://scrapifydatalabs.com/catalog?page=1",
            chunks=(
                CatalogChunkResult(
                    sequence=0,
                    requested_ref="https://scrapifydatalabs.com/catalog?page=1",
                    attempted_at=T0,
                    status=CatalogChunkStatus.FETCH_FAILED,
                    error_code="ConnectError",
                ),
            ),
        )
        assert acquisition.coverage_status == CatalogRunStatus.INCOMPLETE
        assert persist_catalog_acquisition(factory, acquisition, changed_at=T0) == ()

        with factory() as session:
            run = session.scalar(
                select(CatalogRunRow).where(
                    CatalogRunRow.run_key == "m9-first-page-failure"
                )
            )
            assert run is not None
            assert run.status == CatalogRunStatus.INCOMPLETE.value
            assert run.evidence_id is None
            chunk = session.scalar(
                select(CatalogRunChunkRow).where(
                    CatalogRunChunkRow.catalog_run_id == run.id
                )
            )
            assert chunk is not None
            assert chunk.status == CatalogChunkStatus.FETCH_FAILED.value
            assert chunk.evidence_id is None
            assert chunk.error_code == "ConnectError"
    finally:
        engine.dispose()
