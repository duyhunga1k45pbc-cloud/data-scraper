from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from src.acquisition.models import RawEvidence
from src.products.models import StateDecision
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import ProductHistoryRow, ProductObservationRow, ProductRow, RawEvidenceRow
from src.storage.service import persist_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scraping_sandbox_product.html"
URL = "https://scrapingsandbox.com/product/m7-concurrency-product"
SOURCE = "scraping_sandbox"
RECORD_ID = "m7-concurrency-product"
T0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
_PRE_RE = re.compile(r"(<pre>)(.*?)(</pre>)", re.DOTALL)


def _base_payload() -> dict[str, object]:
    body = FIXTURE.read_text(encoding="utf-8")
    match = _PRE_RE.search(body)
    assert match is not None
    payload = json.loads(match.group(2))
    payload["id"] = RECORD_ID
    return payload


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


def _clean(session_factory) -> None:
    with session_factory() as session:
        with session.begin():
            product = session.scalar(
                select(ProductRow).where(
                    ProductRow.source == SOURCE,
                    ProductRow.source_record_id == RECORD_ID,
                )
            )
            if product is not None:
                session.execute(
                    delete(ProductHistoryRow).where(ProductHistoryRow.product_id == product.id)
                )
                session.delete(product)
            session.execute(
                delete(ProductObservationRow).where(
                    ProductObservationRow.source == SOURCE,
                    ProductObservationRow.source_record_id == RECORD_ID,
                )
            )
            session.execute(
                delete(RawEvidenceRow).where(RawEvidenceRow.source_url == URL)
            )


def _run_concurrently(*jobs):
    start = threading.Barrier(len(jobs))
    results: dict[str, object] = {}
    errors: dict[str, BaseException] = {}

    def run(name: str, job) -> None:
        try:
            start.wait(timeout=2.0)
            results[name] = job()
        except BaseException as exc:  # pragma: no cover - diagnostic path
            errors[name] = exc

    threads = [
        threading.Thread(target=run, args=(name, job), name=name)
        for name, job in jobs
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)
        assert not thread.is_alive(), f"{thread.name} deadlocked"

    assert not errors, errors
    return results


@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1" or not os.getenv("DATABASE_URL"),
    reason="set RUN_POSTGRES=1 and DATABASE_URL",
)
def test_m7_concurrent_identical_first_observations_create_once() -> None:
    """INV-14: a missing row is still serialized by product identity."""

    engine = create_database_engine(os.environ["DATABASE_URL"])
    session_factory = create_session_factory(engine)

    try:
        _clean(session_factory)
        payload = _base_payload()

        results = _run_concurrently(
            (
                "m7-create-a",
                lambda: persist_product_evidence(
                    session_factory,
                    _evidence("m7-create-a", payload, T0),
                    changed_at=T0,
                ),
            ),
            (
                "m7-create-b",
                lambda: persist_product_evidence(
                    session_factory,
                    _evidence("m7-create-b", payload, T0),
                    changed_at=T0,
                ),
            ),
        )

        decisions = sorted(run.transition.decision.value for run in results.values())
        assert decisions == [StateDecision.CREATE.value, StateDecision.NO_CHANGE.value]

        with session_factory() as session:
            products = list(
                session.scalars(
                    select(ProductRow).where(
                        ProductRow.source == SOURCE,
                        ProductRow.source_record_id == RECORD_ID,
                    )
                )
            )
            observations = list(
                session.scalars(
                    select(ProductObservationRow)
                    .where(
                        ProductObservationRow.source == SOURCE,
                        ProductObservationRow.source_record_id == RECORD_ID,
                    )
                    .order_by(ProductObservationRow.id)
                )
            )
            assert len(products) == 1
            product = products[0]
            history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.product_id == product.id)
                    .order_by(ProductHistoryRow.id)
                )
            )

            assert len(observations) == 2
            assert [row.state_decision for row in observations].count(
                StateDecision.CREATE.value
            ) == 1
            assert [row.state_decision for row in observations].count(
                StateDecision.NO_CHANGE.value
            ) == 1
            assert [row.decision for row in history] == [StateDecision.CREATE.value]
    finally:
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1" or not os.getenv("DATABASE_URL"),
    reason="set RUN_POSTGRES=1 and DATABASE_URL",
)
def test_m7_concurrent_first_observations_converge_to_newest_state() -> None:
    """Distinct first observations converge regardless of which worker wins first.

    If the older worker wins the identity lock first, history is CREATE -> UPDATE.
    If the newer worker wins first, the older worker becomes STALE. Both executions
    are valid, but the final trusted state must always be the newer observation.
    """

    engine = create_database_engine(os.environ["DATABASE_URL"])
    session_factory = create_session_factory(engine)

    try:
        _clean(session_factory)
        base = _base_payload()
        older_payload = deepcopy(base)
        older_payload["price"] = 144.00
        newer_payload = deepcopy(base)
        newer_payload["price"] = 166.00
        older_time = T0 + timedelta(minutes=3)
        newer_time = T0 + timedelta(minutes=5)

        results = _run_concurrently(
            (
                "m7-older",
                lambda: persist_product_evidence(
                    session_factory,
                    _evidence("m7-older", older_payload, older_time),
                    changed_at=older_time,
                ),
            ),
            (
                "m7-newer",
                lambda: persist_product_evidence(
                    session_factory,
                    _evidence("m7-newer", newer_payload, newer_time),
                    changed_at=newer_time,
                ),
            ),
        )

        decisions = [run.transition.decision for run in results.values()]
        assert decisions.count(StateDecision.CREATE) == 1
        assert sum(
            decision in {StateDecision.UPDATE, StateDecision.STALE}
            for decision in decisions
        ) == 1

        with session_factory() as session:
            product = session.scalar(
                select(ProductRow).where(
                    ProductRow.source == SOURCE,
                    ProductRow.source_record_id == RECORD_ID,
                )
            )
            assert product is not None

            product_count = session.scalar(
                select(func.count())
                .select_from(ProductRow)
                .where(
                    ProductRow.source == SOURCE,
                    ProductRow.source_record_id == RECORD_ID,
                )
            )
            observations = list(
                session.scalars(
                    select(ProductObservationRow)
                    .where(
                        ProductObservationRow.source == SOURCE,
                        ProductObservationRow.source_record_id == RECORD_ID,
                    )
                    .order_by(ProductObservationRow.id)
                )
            )
            history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.product_id == product.id)
                    .order_by(ProductHistoryRow.id)
                )
            )

            assert product_count == 1
            assert product.price == Decimal("166.00")
            assert product.observed_at == newer_time
            assert len(observations) == 2
            assert sum(row.state_decision == StateDecision.CREATE.value for row in observations) == 1
            assert [row.decision for row in history][0] == StateDecision.CREATE.value
            assert [row.decision for row in history].count(StateDecision.CREATE.value) == 1
            assert all(
                row.decision in {StateDecision.CREATE.value, StateDecision.UPDATE.value}
                for row in history
            )
            assert len(history) in {1, 2}
    finally:
        engine.dispose()
