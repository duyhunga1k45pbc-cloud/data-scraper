from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from src.acquisition.models import RawEvidence
from src.products.models import StateDecision
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import ProductHistoryRow, ProductObservationRow, ProductRow, RawEvidenceRow
from src.storage.service import persist_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scraping_sandbox_product.html"
URL = "https://scrapingsandbox.com/product/1"
SOURCE = "scraping_sandbox"
T0 = datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc)
_PRE_RE = re.compile(r"(<pre>)(.*?)(</pre>)", re.DOTALL)


def _base_payload() -> dict[str, object]:
    body = FIXTURE.read_text(encoding="utf-8")
    match = _PRE_RE.search(body)
    assert match is not None
    return json.loads(match.group(2))


def _evidence(evidence_id: str, payload: dict[str, object], at: datetime) -> RawEvidence:
    body = FIXTURE.read_text(encoding="utf-8")
    body = _PRE_RE.sub(
        rf"\1{json.dumps(deepcopy(payload), indent=2)}\3",
        body,
        count=1,
    )
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=URL,
        fetched_at=at,
        status_code=200,
        content_type="text/html",
        body=body,
    )


@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1",
    reason="set RUN_POSTGRES=1",
)
def test_m5_postgres_rejects_late_older_observation_from_trusted_state() -> None:
    engine = create_database_engine(os.environ["DATABASE_URL"])
    session_factory = create_session_factory(engine)

    try:
        with session_factory() as session:
            with session.begin():
                product = session.scalar(
                    select(ProductRow).where(
                        ProductRow.source == SOURCE,
                        ProductRow.source_record_id == "1",
                    )
                )
                if product is not None:
                    session.execute(
                        delete(ProductHistoryRow).where(ProductHistoryRow.product_id == product.id)
                    )
                    session.delete(product)
                session.execute(
                    delete(ProductObservationRow).where(ProductObservationRow.source == SOURCE)
                )
                session.execute(
                    delete(RawEvidenceRow).where(RawEvidenceRow.source_url == URL)
                )

        base = _base_payload()
        newer_time = T0 + timedelta(minutes=5)
        create = persist_product_evidence(
            session_factory,
            _evidence("m5-pg-current", base, newer_time),
            changed_at=newer_time,
        )
        assert create.transition.decision == StateDecision.CREATE

        stale_payload = deepcopy(base)
        stale_payload["price"] = 99.99
        stale = persist_product_evidence(
            session_factory,
            _evidence("m5-pg-stale", stale_payload, T0),
            changed_at=T0 + timedelta(minutes=10),
        )
        assert stale.transition.decision == StateDecision.STALE

        with session_factory() as session:
            product = session.scalar(
                select(ProductRow).where(
                    ProductRow.source == SOURCE,
                    ProductRow.source_record_id == "1",
                )
            )
            assert product is not None
            history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.product_id == product.id)
                    .order_by(ProductHistoryRow.id)
                )
            )
            observations = list(
                session.scalars(
                    select(ProductObservationRow)
                    .where(ProductObservationRow.source == SOURCE)
                    .order_by(ProductObservationRow.id)
                )
            )

            assert product.price == Decimal("155.62")
            assert product.observed_at == newer_time
            assert product.accepted_observation_id == create.observation_id
            assert [row.decision for row in history] == [StateDecision.CREATE.value]
            assert [row.state_decision for row in observations] == [
                StateDecision.CREATE.value,
                StateDecision.STALE.value,
            ]
            assert observations[-1].price == Decimal("99.99")
    finally:
        engine.dispose()
