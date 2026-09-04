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
from src.storage.models import (
    Base,
    ProductHistoryRow,
    ProductObservationRow,
    ProductRow,
    RawEvidenceRow,
)
from src.storage.service import persist_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scraping_sandbox_product.html"
URL = "https://scrapingsandbox.com/product/1"
T0 = datetime(2026, 9, 5, 4, 0, tzinfo=timezone.utc)
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


def _evidence(
    evidence_id: str,
    payload: dict[str, object],
    *,
    fetched_at: datetime,
) -> RawEvidence:
    body = FIXTURE.read_text(encoding="utf-8")
    rendered = json.dumps(deepcopy(payload), indent=2)
    body = _PRE_RE.sub(rf"\1{rendered}\3", body, count=1)
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=URL,
        fetched_at=fetched_at,
        status_code=200,
        content_type="text/html",
        body=body,
    )


def test_m4_persistence_keeps_only_meaningful_semantic_transitions_in_history() -> None:
    session_factory = _factory()

    base = _base_payload()
    create_run = persist_product_evidence(
        session_factory,
        _evidence("m4-db-create", base, fetched_at=T0),
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
        _evidence("m4-db-update", changed, fetched_at=t1),
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
        _evidence("m4-db-reordered", reordered, fetched_at=t2),
        changed_at=t2,
    )
    assert no_change_run.transition.decision == StateDecision.NO_CHANGE

    compare_removed = deepcopy(changed)
    compare_removed["compareAtPrice"] = None
    t3 = T0 + timedelta(minutes=3)
    second_update = persist_product_evidence(
        session_factory,
        _evidence("m4-db-compare-removed", compare_removed, fetched_at=t3),
        changed_at=t3,
    )
    assert second_update.transition.decision == StateDecision.UPDATE

    with session_factory() as session:
        product = session.scalar(select(ProductRow))
        history = list(session.scalars(select(ProductHistoryRow).order_by(ProductHistoryRow.id)))
        observations = list(
            session.scalars(select(ProductObservationRow).order_by(ProductObservationRow.id))
        )
        evidence = list(session.scalars(select(RawEvidenceRow).order_by(RawEvidenceRow.fetched_at)))

        assert product is not None
        assert product.price == Decimal("149.99")
        assert product.compare_at_price is None
        changed_variant = next(
            item for item in product.variants if item["key"] == "sku:SKU-HEA-0001-PIN-XXL"
        )
        assert changed_variant["availability"] == "OUT_OF_STOCK"

        assert [row.decision for row in history] == ["CREATE", "UPDATE", "UPDATE"]
        assert len(observations) == 4
        assert [row.state_decision for row in observations] == [
            "CREATE",
            "UPDATE",
            "NO_CHANGE",
            "UPDATE",
        ]
        assert len(evidence) == 4

        first_update = history[1]
        assert first_update.previous_state is not None
        assert first_update.previous_state["price"] == "155.62"
        assert first_update.new_state["price"] == "149.99"

        second_history_update = history[2]
        assert second_history_update.previous_state is not None
        assert second_history_update.previous_state["compare_at_price"] == "206.69"
        assert second_history_update.new_state["compare_at_price"] is None
