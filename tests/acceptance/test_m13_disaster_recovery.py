from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.acquisition.models import RawEvidence
from src.catalogs.acquisition import single_payload_catalog_acquisition
from src.scrapify_js.parser import parse_catalog
from src.storage.database import create_database_engine, create_session_factory
from src.storage.disaster_recovery import (
    RecoveryError,
    export_recovery_bundle,
    recover_bundle_into_session,
    validate_recovery_bundle,
)
from src.storage.models import Base, ProductRow
from src.storage.replay import replay_source_projection
from src.storage.service import persist_catalog_acquisition


SOURCE = "scrapify_js"
SCOPE = "m13-acceptance-full-catalog"
URL = "https://scrapifydatalabs.com/data/m13-products.json"
T0 = datetime(2026, 9, 5, 18, 0, tzinfo=timezone.utc)


def _factory(tmp_path, name: str):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")
    Base.metadata.create_all(engine)
    return engine, create_session_factory(engine)


def _acquisition(run_key: str, at: datetime, *, price: float, include_b: bool = True):
    products = [
        {
            "id": "m13-a",
            "title": "M13 A",
            "category": "M13",
            "price": price,
            "currency": "USD",
            "in_stock": True,
        }
    ]
    if include_b:
        products.append(
            {
                "id": "m13-b",
                "title": "M13 B",
                "category": "M13",
                "price": 20.0,
                "currency": "USD",
                "in_stock": False,
            }
        )
    body = json.dumps({"products": products})
    evidence = RawEvidence.capture(
        evidence_id=f"{run_key}-evidence",
        source_url=URL,
        fetched_at=at,
        status_code=200,
        content_type="application/json",
        body=body,
    )
    return single_payload_catalog_acquisition(
        source=SOURCE,
        scope_key=SCOPE,
        evidence=evidence,
        observations=parse_catalog(evidence),
        run_key=run_key,
    )


def _seed(factory) -> None:
    persist_catalog_acquisition(
        factory,
        _acquisition("m13-initial", T0, price=10.0),
        changed_at=T0 + timedelta(seconds=1),
    )
    persist_catalog_acquisition(
        factory,
        _acquisition("m13-update", T0 + timedelta(minutes=5), price=11.0),
        changed_at=T0 + timedelta(minutes=5, seconds=1),
    )
    persist_catalog_acquisition(
        factory,
        _acquisition(
            "m13-disappear-b",
            T0 + timedelta(minutes=10),
            price=11.0,
            include_b=False,
        ),
        changed_at=T0 + timedelta(minutes=10, seconds=1),
    )


def _semantic_products(factory):
    with factory() as session:
        rows = list(
            session.scalars(
                select(ProductRow).where(ProductRow.source == SOURCE).order_by(ProductRow.identity_key)
            )
        )
        return [
            (
                row.identity_key,
                str(row.price),
                row.presence_status,
                row.presence_observed_at,
                row.accepted_observation_id,
            )
            for row in rows
        ]


def test_m13_bundle_excludes_projection_and_detects_tampering(tmp_path) -> None:
    engine, factory = _factory(tmp_path, "m13-source.db")
    try:
        _seed(factory)
        with factory() as session:
            bundle = export_recovery_bundle(session)

        assert "products" not in bundle["tables"]
        assert len(bundle["tables"]["product_history"]) == 4
        assert len(bundle["tables"]["raw_evidence"]) == 3
        validate_recovery_bundle(bundle)

        tampered = copy.deepcopy(bundle)
        tampered["tables"]["raw_evidence"][0]["body"] += " "
        with pytest.raises(RecoveryError, match="hash mismatch"):
            validate_recovery_bundle(tampered)
    finally:
        engine.dispose()


def test_m13_recovers_clean_database_from_durable_bundle(tmp_path) -> None:
    source_engine, source_factory = _factory(tmp_path, "m13-source-recover.db")
    target_engine, target_factory = _factory(tmp_path, "m13-target-recover.db")
    try:
        _seed(source_factory)
        before = _semantic_products(source_factory)
        with source_factory() as session:
            bundle = export_recovery_bundle(session)

        with target_factory() as session:
            with session.begin():
                report = recover_bundle_into_session(session, bundle)
        assert report.is_consistent
        assert report.stage == "RECOVERED_DATABASE"
        assert report.products == 2
        assert report.issues == ()

        after = _semantic_products(target_factory)
        assert after == before
        with target_factory() as session:
            replay = replay_source_projection(session, source=SOURCE)
            assert replay.is_consistent
            assert replay.issues == ()
    finally:
        source_engine.dispose()
        target_engine.dispose()


def test_m13_restore_fails_closed_when_target_is_not_empty(tmp_path) -> None:
    source_engine, source_factory = _factory(tmp_path, "m13-source-nonempty.db")
    target_engine, target_factory = _factory(tmp_path, "m13-target-nonempty.db")
    try:
        _seed(source_factory)
        _seed(target_factory)
        with source_factory() as session:
            bundle = export_recovery_bundle(session)

        with target_factory() as session:
            with session.begin():
                report = recover_bundle_into_session(session, bundle)
        assert not report.is_consistent
        assert report.stage == "RESTORE_DURABLE_STATE"
        assert [item.code for item in report.issues] == ["RESTORE_FAILED"]
        assert "not empty" in report.issues[0].message
    finally:
        source_engine.dispose()
        target_engine.dispose()
