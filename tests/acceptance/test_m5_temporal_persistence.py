from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.acquisition.models import RawEvidence
from src.products.models import StateDecision
from src.storage.models import Base, ProductHistoryRow, ProductObservationRow, ProductRow, RawEvidenceRow
from src.storage.service import persist_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scraping_sandbox_product.html"
URL = "https://scrapingsandbox.com/product/1"
T0 = datetime(2026, 9, 5, 7, 0, tzinfo=timezone.utc)
_PRE_RE = re.compile(r"(<pre>)(.*?)(</pre>)", re.DOTALL)


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


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


def test_m5_stale_observation_is_traced_without_mutating_state_or_history() -> None:
    session_factory = _factory()
    base = _base_payload()
    t1 = T0 + timedelta(minutes=5)

    create = persist_product_evidence(
        session_factory,
        _evidence("m5-db-current", base, t1),
        changed_at=t1,
    )
    assert create.transition.decision == StateDecision.CREATE
    assert create.observation_id is not None

    stale_payload = deepcopy(base)
    stale_payload["price"] = 99.99
    stale = persist_product_evidence(
        session_factory,
        _evidence("m5-db-stale", stale_payload, T0),
        changed_at=T0 + timedelta(minutes=10),
    )
    assert stale.transition.decision == StateDecision.STALE

    with session_factory() as session:
        product = session.scalar(select(ProductRow))
        history = list(session.scalars(select(ProductHistoryRow).order_by(ProductHistoryRow.id)))
        observations = list(
            session.scalars(select(ProductObservationRow).order_by(ProductObservationRow.id))
        )
        evidence = list(session.scalars(select(RawEvidenceRow).order_by(RawEvidenceRow.id)))

        assert product is not None
        assert product.price == Decimal("155.62")
        assert product.observed_at.replace(tzinfo=timezone.utc) == t1
        assert product.accepted_observation_id == create.observation_id
        assert [row.decision for row in history] == [StateDecision.CREATE.value]
        assert [row.state_decision for row in observations] == [
            StateDecision.CREATE.value,
            StateDecision.STALE.value,
        ]
        assert observations[-1].price == Decimal("99.99")
        assert len(evidence) == 2
