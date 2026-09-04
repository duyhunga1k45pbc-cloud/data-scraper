from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.acquisition.models import RawEvidence
from src.catalogs.models import CatalogAcquisition, CatalogChunkResult, CatalogChunkStatus
from src.products import validation as product_validation
from src.products.models import ProductObservation, ProductPresenceStatus
from src.storage.models import Base, CatalogRunChunkRow, CatalogRunRow, ProductRow, RawEvidenceRow
from src.storage.replay import replay_source_projection
from src.storage.service import persist_catalog_acquisition


SOURCE = "m10_test_source"
SCOPE = "m10-replay-scope"
BASE = "https://m10.test/catalog"
EXTRACTOR_VERSION = "m10-test-v1"
A = "m10-a"
B = "m10-b"
C = "m10-c"
T0 = datetime(2026, 9, 5, 6, 0, tzinfo=timezone.utc)


def _factory(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'm10.db'}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


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
        title_raw=f"M10 {record_id}",
        price_raw="10.00",
        availability_raw="Out of stock",
        category_raw="M10",
        currency_raw="USD",
        source_record_id_raw=record_id,
    )


def _complete_run(
    *,
    run_key: str,
    at: datetime,
    ids: tuple[str, ...],
) -> CatalogAcquisition:
    evidence = _evidence(f"{run_key}-evidence", at)
    return CatalogAcquisition(
        run_key=run_key,
        source=SOURCE,
        scope_key=SCOPE,
        start_ref=evidence.source_url,
        chunks=(
            CatalogChunkResult(
                sequence=0,
                requested_ref=evidence.source_url,
                attempted_at=evidence.fetched_at,
                status=CatalogChunkStatus.SUCCESS,
                evidence=evidence,
                observations=tuple(_observation(evidence, item) for item in ids),
                next_ref=None,
            ),
        ),
    )


def _seed_timeline(factory) -> None:
    persist_catalog_acquisition(
        factory,
        _complete_run(run_key="m10-initial", at=T0, ids=(A, B, C)),
        changed_at=T0 + timedelta(seconds=1),
    )
    # Equivalent direct presence: no history, but freshness must advance.
    persist_catalog_acquisition(
        factory,
        _complete_run(
            run_key="m10-unchanged",
            at=T0 + timedelta(minutes=5),
            ids=(A, B, C),
        ),
        changed_at=T0 + timedelta(minutes=5, seconds=1),
    )
    # C disappears with a proven complete run.
    persist_catalog_acquisition(
        factory,
        _complete_run(
            run_key="m10-disappear",
            at=T0 + timedelta(minutes=10),
            ids=(A, B),
        ),
        changed_at=T0 + timedelta(minutes=10, seconds=1),
    )
    # Repeated absence must refresh C without duplicate history.
    persist_catalog_acquisition(
        factory,
        _complete_run(
            run_key="m10-repeat-absence",
            at=T0 + timedelta(minutes=15),
            ids=(A, B),
        ),
        changed_at=T0 + timedelta(minutes=15, seconds=1),
    )


def test_m10_replay_reconstructs_current_projection_including_no_history_freshness(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setitem(product_validation.SOURCE_HOSTS, SOURCE, "m10.test")
    engine, factory = _factory(tmp_path)
    try:
        _seed_timeline(factory)

        with factory() as session:
            report = replay_source_projection(session, source=SOURCE)
            assert report.is_consistent
            assert report.issues == ()
            assert len(report.products) == 3

            c = next(item for item in report.products if item.identity_key == f"id:{C}")
            assert c.expected_state["presence_status"] == ProductPresenceStatus.DISAPPEARED.value
            assert c.expected_state["presence_observed_at"] == (
                T0 + timedelta(minutes=15)
            ).isoformat()
            assert len(c.history_ids) == 2
    finally:
        engine.dispose()


def test_m10_replay_detects_current_projection_drift(tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(product_validation.SOURCE_HOSTS, SOURCE, "m10.test")
    engine, factory = _factory(tmp_path)
    try:
        _seed_timeline(factory)
        with factory() as session:
            with session.begin():
                row = session.scalar(
                    select(ProductRow).where(
                        ProductRow.source == SOURCE,
                        ProductRow.source_record_id == A,
                    )
                )
                assert row is not None
                row.price = Decimal("99.00")

        with factory() as session:
            report = replay_source_projection(session, source=SOURCE)
            assert not report.is_consistent
            assert "CURRENT_PROJECTION_MISMATCH" in {item.code for item in report.issues}
    finally:
        engine.dispose()


def test_m10_replay_detects_raw_evidence_tampering(tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(product_validation.SOURCE_HOSTS, SOURCE, "m10.test")
    engine, factory = _factory(tmp_path)
    try:
        _seed_timeline(factory)
        with factory() as session:
            with session.begin():
                evidence = session.get(RawEvidenceRow, "m10-initial-evidence")
                assert evidence is not None
                evidence.body = '{"tampered":true}'

        with factory() as session:
            report = replay_source_projection(session, source=SOURCE)
            assert not report.is_consistent
            assert "RAW_EVIDENCE_HASH_MISMATCH" in {item.code for item in report.issues}
    finally:
        engine.dispose()


def test_m10_replay_rederives_disappearance_coverage_proof(tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(product_validation.SOURCE_HOSTS, SOURCE, "m10.test")
    engine, factory = _factory(tmp_path)
    try:
        _seed_timeline(factory)
        with factory() as session:
            with session.begin():
                run = session.scalar(
                    select(CatalogRunRow).where(CatalogRunRow.run_key == "m10-disappear")
                )
                assert run is not None
                chunk = session.scalar(
                    select(CatalogRunChunkRow).where(
                        CatalogRunChunkRow.catalog_run_id == run.id
                    )
                )
                assert chunk is not None
                chunk.next_ref = "https://m10.test/catalog/missing-next-page"

        with factory() as session:
            report = replay_source_projection(session, source=SOURCE)
            assert not report.is_consistent
            assert "INVALID_DISAPPEARANCE_COVERAGE_PROOF" in {
                item.code for item in report.issues
            }
    finally:
        engine.dispose()


def test_m10_replay_normalizes_pre_m8_history_snapshot_schema(tmp_path, monkeypatch) -> None:
    """Relational migrations backfilled current rows, not old JSON snapshots."""

    monkeypatch.setitem(product_validation.SOURCE_HOSTS, SOURCE, "m10.test")
    engine, factory = _factory(tmp_path)
    try:
        initial = _complete_run(run_key="m10-legacy", at=T0, ids=(A,))
        persist_catalog_acquisition(factory, initial, changed_at=T0 + timedelta(seconds=1))

        from src.storage.models import ProductHistoryRow

        with factory() as session:
            with session.begin():
                history = session.scalar(select(ProductHistoryRow))
                assert history is not None
                legacy = dict(history.new_state)
                for key in (
                    "identity_key",
                    "compare_at_price",
                    "sku",
                    "categories",
                    "variants",
                    "presence_status",
                    "presence_observed_at",
                ):
                    legacy.pop(key, None)
                history.new_state = legacy

        with factory() as session:
            report = replay_source_projection(session, source=SOURCE)
            assert report.is_consistent
            assert report.issues == ()
    finally:
        engine.dispose()

def test_m10_replay_treats_decimal_scale_as_representation_not_state(tmp_path, monkeypatch) -> None:
    """PostgreSQL NUMERIC scale must not create false replay divergence."""

    monkeypatch.setitem(product_validation.SOURCE_HOSTS, SOURCE, "m10.test")
    engine, factory = _factory(tmp_path)
    try:
        evidence = _evidence("m10-decimal-scale-evidence", T0)
        observation = ProductObservation(
            evidence_id=evidence.id,
            extractor_version=EXTRACTOR_VERSION,
            source=SOURCE,
            source_url=evidence.source_url,
            observed_at=evidence.fetched_at,
            title_raw="M10 decimal scale",
            price_raw="199.0",
            availability_raw="Out of stock",
            category_raw="M10",
            currency_raw="USD",
            source_record_id_raw="m10-decimal-scale",
        )
        acquisition = CatalogAcquisition(
            run_key="m10-decimal-scale",
            source=SOURCE,
            scope_key=SCOPE,
            start_ref=evidence.source_url,
            chunks=(
                CatalogChunkResult(
                    sequence=0,
                    requested_ref=evidence.source_url,
                    attempted_at=evidence.fetched_at,
                    status=CatalogChunkStatus.SUCCESS,
                    evidence=evidence,
                    observations=(observation,),
                    next_ref=None,
                ),
            ),
        )
        persist_catalog_acquisition(
            factory,
            acquisition,
            changed_at=T0 + timedelta(seconds=1),
        )

        from src.storage.models import ProductHistoryRow

        with factory() as session:
            row = session.scalar(select(ProductRow))
            history = session.scalar(select(ProductHistoryRow))
            assert row is not None
            assert history is not None
            assert row.price == Decimal("199.00")
            assert history.new_state["price"] == "199.0"

            report = replay_source_projection(session, source=SOURCE)
            assert report.is_consistent
            assert report.issues == ()
    finally:
        engine.dispose()

