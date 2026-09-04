from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select, update

from src.acquisition.models import RawEvidence
from src.catalogs.acquisition import single_payload_catalog_acquisition
from src.products.models import ProductPresenceStatus
from src.scrapify_js.parser import parse_catalog
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import Base, ProductHistoryRow, ProductRow, RawEvidenceRow
from src.storage.rebuild import (
    build_source_projection_from_ledger,
    rebuild_source_projection_in_place,
)
from src.storage.replay import replay_source_projection
from src.storage.service import persist_catalog_acquisition


SOURCE = "scrapify_js"
SCOPE = "m12-acceptance-full-catalog"
URL = "https://scrapifydatalabs.com/data/m12-products.json"
T0 = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


def _factory(tmp_path, name: str):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")
    Base.metadata.create_all(engine)
    return engine, create_session_factory(engine)


def _products(*, a_price: str = "10.0", include_c: bool = True) -> list[dict]:
    values = [
        {
            "id": "m12-a",
            "title": "M12 A",
            "category": "M12",
            "price": float(a_price),
            "currency": "USD",
            "in_stock": True,
        },
        {
            "id": "m12-b",
            "title": "M12 B",
            "category": "M12",
            "price": 20.0,
            "currency": "USD",
            "in_stock": True,
        },
    ]
    if include_c:
        values.append(
            {
                "id": "m12-c",
                "title": "M12 C",
                "category": "M12",
                "price": 30.0,
                "currency": "USD",
                "in_stock": False,
            }
        )
    return values


def _run(
    *,
    run_key: str,
    at: datetime,
    a_price: str = "10.0",
    include_c: bool = True,
):
    body = json.dumps({"products": _products(a_price=a_price, include_c=include_c)})
    evidence = RawEvidence.capture(
        evidence_id=f"{run_key}-evidence",
        source_url=URL,
        fetched_at=at,
        status_code=200,
        content_type="application/json",
        body=body,
    )
    observations = parse_catalog(evidence)
    return single_payload_catalog_acquisition(
        source=SOURCE,
        scope_key=SCOPE,
        evidence=evidence,
        observations=observations,
        run_key=run_key,
    )


def _seed(factory) -> None:
    persist_catalog_acquisition(
        factory,
        _run(run_key="m12-initial", at=T0),
        changed_at=T0 + timedelta(seconds=1),
    )
    persist_catalog_acquisition(
        factory,
        _run(run_key="m12-unchanged", at=T0 + timedelta(minutes=5)),
        changed_at=T0 + timedelta(minutes=5, seconds=1),
    )
    persist_catalog_acquisition(
        factory,
        _run(
            run_key="m12-update-a",
            at=T0 + timedelta(minutes=7),
            a_price="11.0",
        ),
        changed_at=T0 + timedelta(minutes=7, seconds=1),
    )
    persist_catalog_acquisition(
        factory,
        _run(
            run_key="m12-disappear-c",
            at=T0 + timedelta(minutes=10),
            a_price="11.0",
            include_c=False,
        ),
        changed_at=T0 + timedelta(minutes=10, seconds=1),
    )
    persist_catalog_acquisition(
        factory,
        _run(
            run_key="m12-repeat-absence",
            at=T0 + timedelta(minutes=15),
            a_price="11.0",
            include_c=False,
        ),
        changed_at=T0 + timedelta(minutes=15, seconds=1),
    )


def _empty_projection(factory) -> None:
    with factory() as session:
        with session.begin():
            session.execute(
                update(ProductHistoryRow)
                .where(ProductHistoryRow.source == SOURCE)
                .values(product_id=None)
            )
            session.execute(delete(ProductRow).where(ProductRow.source == SOURCE))


def test_m12_ledger_rebuild_does_not_require_products_projection(tmp_path) -> None:
    engine, factory = _factory(tmp_path, "m12-ledger.db")
    try:
        _seed(factory)
        _empty_projection(factory)

        with factory() as session:
            assert list(
                session.scalars(select(ProductRow).where(ProductRow.source == SOURCE))
            ) == []
            ledger = build_source_projection_from_ledger(session, source=SOURCE)
            missing_projection = replay_source_projection(session, source=SOURCE)

        assert not missing_projection.is_consistent
        assert "MISSING_CURRENT_PROJECTION" in {
            item.code for item in missing_projection.issues
        }
        assert ledger.is_consistent
        assert ledger.issues == ()
        assert len(ledger.products) == 3
        a = next(item for item in ledger.products if item.identity_key == "id:m12-a")
        c = next(item for item in ledger.products if item.identity_key == "id:m12-c")
        assert Decimal(a.expected_state["price"]) == Decimal("11")
        assert c.expected_state["presence_status"] == ProductPresenceStatus.DISAPPEARED.value
        assert c.expected_state["presence_observed_at"] == (
            T0 + timedelta(minutes=15)
        ).isoformat()
    finally:
        engine.dispose()


def test_m12_rebuilds_empty_projection_and_relinks_original_history(tmp_path) -> None:
    engine, factory = _factory(tmp_path, "m12-rebuild.db")
    try:
        _seed(factory)
        with factory() as session:
            history_ids = tuple(
                session.scalars(
                    select(ProductHistoryRow.id)
                    .where(ProductHistoryRow.source == SOURCE)
                    .order_by(ProductHistoryRow.id)
                )
            )
        assert len(history_ids) == 5

        _empty_projection(factory)

        with factory() as session:
            with session.begin():
                report = rebuild_source_projection_in_place(session, source=SOURCE)
            assert report.is_consistent
            assert report.issues == ()
            assert len(report.products) == 3
            assert all(item.old_product_id is None for item in report.products)
            assert report.history_rows == len(history_ids)

        with factory() as session:
            rows = list(
                session.scalars(
                    select(ProductRow)
                    .where(ProductRow.source == SOURCE)
                    .order_by(ProductRow.identity_key)
                )
            )
            assert len(rows) == 3
            linked_history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.source == SOURCE)
                    .order_by(ProductHistoryRow.id)
                )
            )
            assert tuple(item.id for item in linked_history) == history_ids
            assert all(item.product_id is not None for item in linked_history)
            replay = replay_source_projection(session, source=SOURCE)
            assert replay.is_consistent
            assert replay.issues == ()
    finally:
        engine.dispose()


def test_m12_fails_closed_before_projection_delete_when_evidence_is_invalid(tmp_path) -> None:
    engine, factory = _factory(tmp_path, "m12-fail-closed.db")
    try:
        _seed(factory)
        with factory() as session:
            before_ids = tuple(
                session.scalars(
                    select(ProductRow.id)
                    .where(ProductRow.source == SOURCE)
                    .order_by(ProductRow.identity_key)
                )
            )
            before_links = tuple(
                session.scalars(
                    select(ProductHistoryRow.product_id)
                    .where(ProductHistoryRow.source == SOURCE)
                    .order_by(ProductHistoryRow.id)
                )
            )

        with factory() as session:
            with session.begin():
                evidence = session.get(RawEvidenceRow, "m12-initial-evidence")
                assert evidence is not None
                evidence.body = evidence.body + " "

        with factory() as session:
            with session.begin():
                report = rebuild_source_projection_in_place(session, source=SOURCE)

        assert not report.is_consistent
        assert "EXTRACTION_RAW_EVIDENCE_HASH_MISMATCH" in {
            item.code for item in report.issues
        }

        with factory() as session:
            after_ids = tuple(
                session.scalars(
                    select(ProductRow.id)
                    .where(ProductRow.source == SOURCE)
                    .order_by(ProductRow.identity_key)
                )
            )
            after_links = tuple(
                session.scalars(
                    select(ProductHistoryRow.product_id)
                    .where(ProductHistoryRow.source == SOURCE)
                    .order_by(ProductHistoryRow.id)
                )
            )
        assert after_ids == before_ids
        assert after_links == before_links
    finally:
        engine.dispose()
