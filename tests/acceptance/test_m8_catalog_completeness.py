from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.acquisition.models import RawEvidence
from src.products.models import ProductPresenceStatus, StateDecision
from src.scrapify_js.parser import parse_catalog
from src.storage.models import Base, CatalogRunRow, ProductHistoryRow, ProductRow
from src.storage.service import CatalogRunStatus, persist_catalog_observations


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scrapify_products.json"
URL = "https://scrapifydatalabs.com/data/products.json"
SOURCE = "scrapify_js"
T0 = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


def _body(record_ids: set[str]) -> str:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["products"] = [
        item for item in payload["products"] if item["id"] in record_ids
    ]
    return json.dumps(payload)


def _evidence(evidence_id: str, record_ids: set[str], at: datetime) -> RawEvidence:
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=URL,
        fetched_at=at,
        status_code=200,
        content_type="application/json",
        body=_body(record_ids),
    )


def _run(factory, evidence_id: str, ids: set[str], at: datetime, *, complete: bool):
    evidence = _evidence(evidence_id, ids, at)
    return persist_catalog_observations(
        factory,
        evidence,
        parse_catalog(evidence),
        source=SOURCE,
        scope_key="full-catalog",
        complete=complete,
        changed_at=at,
    )


def _factory(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'm8.db'}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_m8_incomplete_catalog_cannot_disappear_missing_product(tmp_path) -> None:
    engine, factory = _factory(tmp_path)
    try:
        _run(factory, "m8-full-1", {"p-1001", "p-1002", "p-1003"}, T0, complete=True)
        _run(
            factory,
            "m8-partial",
            {"p-1001", "p-1002"},
            T0 + timedelta(minutes=5),
            complete=False,
        )

        with factory() as session:
            missing = session.scalar(
                select(ProductRow).where(ProductRow.source_record_id == "p-1003")
            )
            runs = list(session.scalars(select(CatalogRunRow).order_by(CatalogRunRow.id)))
            assert missing is not None
            assert missing.presence_status == ProductPresenceStatus.ACTIVE.value
            assert [run.status for run in runs] == [
                CatalogRunStatus.COMPLETE.value,
                CatalogRunStatus.INCOMPLETE.value,
            ]
    finally:
        engine.dispose()


def test_m8_complete_catalog_disappears_once_and_reappearance_is_explicit(tmp_path) -> None:
    engine, factory = _factory(tmp_path)
    try:
        _run(factory, "m8-full-1", {"p-1001", "p-1002", "p-1003"}, T0, complete=True)
        t1 = T0 + timedelta(minutes=5)
        _run(factory, "m8-full-2", {"p-1001", "p-1002"}, t1, complete=True)

        with factory() as session:
            product = session.scalar(
                select(ProductRow).where(ProductRow.source_record_id == "p-1003")
            )
            assert product is not None
            assert product.presence_status == ProductPresenceStatus.DISAPPEARED.value
            assert product.presence_observed_at.replace(tzinfo=timezone.utc) == t1
            history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.product_id == product.id)
                    .order_by(ProductHistoryRow.id)
                )
            )
            assert [row.decision for row in history] == [
                StateDecision.CREATE.value,
                StateDecision.DISAPPEARED.value,
            ]
            assert history[-1].observation_id is None
            assert history[-1].catalog_run_id is not None

        # A later complete run still missing the product refreshes absence evidence
        # but must not create a second disappearance history event.
        t2 = T0 + timedelta(minutes=10)
        _run(factory, "m8-full-3", {"p-1001", "p-1002"}, t2, complete=True)
        with factory() as session:
            product = session.scalar(
                select(ProductRow).where(ProductRow.source_record_id == "p-1003")
            )
            assert product is not None
            assert product.presence_observed_at.replace(tzinfo=timezone.utc) == t2
            history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.product_id == product.id)
                    .order_by(ProductHistoryRow.id)
                )
            )
            assert [row.decision for row in history] == [
                StateDecision.CREATE.value,
                StateDecision.DISAPPEARED.value,
            ]

        t3 = T0 + timedelta(minutes=15)
        results = _run(
            factory,
            "m8-full-4",
            {"p-1001", "p-1002", "p-1003"},
            t3,
            complete=True,
        )
        p3_run = next(run for run in results if run.normalized.source_record_id == "p-1003")
        assert p3_run.transition.decision == StateDecision.REAPPEARED

        with factory() as session:
            product = session.scalar(
                select(ProductRow).where(ProductRow.source_record_id == "p-1003")
            )
            assert product is not None
            assert product.presence_status == ProductPresenceStatus.ACTIVE.value
            assert product.presence_observed_at.replace(tzinfo=timezone.utc) == t3
            history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.product_id == product.id)
                    .order_by(ProductHistoryRow.id)
                )
            )
            assert [row.decision for row in history] == [
                StateDecision.CREATE.value,
                StateDecision.DISAPPEARED.value,
                StateDecision.REAPPEARED.value,
            ]
            assert history[-1].observation_id is not None
            assert history[-1].catalog_run_id is None
    finally:
        engine.dispose()


def test_m8_newer_no_change_presence_blocks_older_missing_snapshot(tmp_path) -> None:
    engine, factory = _factory(tmp_path)
    try:
        _run(factory, "m8-fresh-1", {"p-1001", "p-1002", "p-1003"}, T0, complete=True)
        newer = T0 + timedelta(minutes=10)
        _run(factory, "m8-fresh-2", {"p-1001", "p-1002", "p-1003"}, newer, complete=True)

        older = T0 + timedelta(minutes=5)
        _run(factory, "m8-delayed-old", {"p-1001", "p-1002"}, older, complete=True)

        with factory() as session:
            product = session.scalar(
                select(ProductRow).where(ProductRow.source_record_id == "p-1003")
            )
            assert product is not None
            assert product.presence_status == ProductPresenceStatus.ACTIVE.value
            assert product.presence_observed_at.replace(tzinfo=timezone.utc) == newer
            history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.product_id == product.id)
                    .order_by(ProductHistoryRow.id)
                )
            )
            assert [row.decision for row in history] == [StateDecision.CREATE.value]
    finally:
        engine.dispose()
