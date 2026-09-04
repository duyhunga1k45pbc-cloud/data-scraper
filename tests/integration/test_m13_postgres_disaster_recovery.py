from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from src.acquisition.models import RawEvidence
from src.extractors.registry import ExtractorRuntime, RUNTIME_REGISTRY
from src.products.models import ProductObservation
from src.products import validation as product_validation
from src.storage.database import create_session_factory
from src.storage.disaster_recovery import verify_disaster_recovery
from src.storage.models import Base
from src.storage.service import persist_product_observations


SOURCE = "m13_pg_source"
VERSION = "m13-pg-v1"
T0 = datetime(2026, 9, 5, 20, 0, tzinfo=timezone.utc)


def _extract(evidence: RawEvidence) -> tuple[ProductObservation, ...]:
    payload = json.loads(evidence.body)
    return (
        ProductObservation(
            evidence_id=evidence.id,
            extractor_version=VERSION,
            source=SOURCE,
            source_url=evidence.source_url,
            observed_at=evidence.fetched_at,
            title_raw=payload["title"],
            price_raw=str(payload["price"]),
            currency_raw="USD",
            availability_raw="Out of stock",
            category_raw="M13",
            source_record_id_raw="m13-pg-1",
        ),
    )


@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1" or not os.getenv("DATABASE_URL"),
    reason="set RUN_POSTGRES=1 and DATABASE_URL",
)
def test_m13_postgres_recovers_into_fresh_schema_and_rolls_back(monkeypatch) -> None:
    database_url = os.environ["DATABASE_URL"]
    schema = f"m13_source_{uuid4().hex}"
    admin = create_engine(database_url)
    source_engine = None

    monkeypatch.setitem(product_validation.SOURCE_HOSTS, SOURCE, "m13-pg.test")
    monkeypatch.setitem(
        RUNTIME_REGISTRY,
        (SOURCE, VERSION),
        ExtractorRuntime(
            source=SOURCE,
            version=VERSION,
            implementation="tests.integration.test_m13_postgres_disaster_recovery:_extract",
            extract=_extract,
        ),
    )

    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))

        source_engine = create_engine(
            database_url,
            connect_args={"options": f"-csearch_path={schema}"},
        )
        Base.metadata.create_all(source_engine)
        factory = create_session_factory(source_engine)

        body = json.dumps({"title": "M13 PG", "price": "42.50"})
        evidence = RawEvidence.capture(
            evidence_id="m13-pg-evidence",
            source_url="https://m13-pg.test/product/1",
            fetched_at=T0,
            status_code=200,
            content_type="application/json",
            body=body,
        )
        persist_product_observations(
            factory,
            evidence,
            _extract(evidence),
            changed_at=T0,
        )

        report = verify_disaster_recovery(source_engine)
        assert report.is_consistent
        assert report.status == "CONSISTENT"
        assert report.stage == "CLEAN_SCHEMA_RECOVERY"
        assert report.sources == (SOURCE,)
        assert report.products == 1
        assert report.rolled_back is True
        assert report.issues == ()
        assert report.durable_rows["raw_evidence"] == 1
        assert report.durable_rows["product_observations"] == 1
        assert report.durable_rows["product_history"] == 1
    finally:
        if source_engine is not None:
            source_engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
