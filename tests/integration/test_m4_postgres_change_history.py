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
T0 = datetime(2026, 9, 5, 5, 0, tzinfo=timezone.utc)
_PRE_RE = re.compile(r"(<pre>)(.*?)(</pre>)", re.DOTALL)


def _base_payload() -> dict[str, object]:
    body = FIXTURE.read_text(encoding="utf-8")
    match = _PRE_RE.search(body)
    assert match is not None
    return json.loads(match.group(2))


def _evidence(evidence_id: str, payload: dict[str, object], at: datetime) -> RawEvidence:
    body = FIXTURE.read_text(encoding="utf-8")
    body = _PRE_RE.sub(rf"\1{json.dumps(deepcopy(payload), indent=2)}\3", body, count=1)
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
def test_m4_postgres_tracks_meaningful_changes_without_order_noise() -> None:
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
        create_run = persist_product_evidence(
            session_factory,
            _evidence("m4-pg-create", base, T0),
            changed_at=T0,
        )
        assert create_run.transition.decision == StateDecision.CREATE

        changed = deepcopy(base)
        changed["price"] = 149.99
        variants = changed["variants"]
        assert isinstance(variants, list)
        assert isinstance(variants[0], dict)
        variants[0]["inStock"] = False
        t1 = T0 + timedelta(minutes=1)
        update_run = persist_product_evidence(
            session_factory,
            _evidence("m4-pg-update", changed, t1),
            changed_at=t1,
        )
        assert update_run.transition.decision == StateDecision.UPDATE

        reordered = deepcopy(changed)
        reordered_variants = reordered["variants"]
        assert isinstance(reordered_variants, list)
        reordered_variants.reverse()
        t2 = T0 + timedelta(minutes=2)
        no_change_run = persist_product_evidence(
            session_factory,
            _evidence("m4-pg-reorder", reordered, t2),
            changed_at=t2,
        )
        assert no_change_run.transition.decision == StateDecision.NO_CHANGE

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

            assert product.price == Decimal("149.99")
            assert [row.decision for row in history] == ["CREATE", "UPDATE"]
            assert [row.state_decision for row in observations] == [
                "CREATE",
                "UPDATE",
                "NO_CHANGE",
            ]
    finally:
        engine.dispose()
