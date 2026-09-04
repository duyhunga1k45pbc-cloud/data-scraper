from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from src.acquisition.models import RawEvidence
from src.books.models import StateDecision
from src.storage import repositories
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import Base, BookHistoryRow, BookObservationRow, BookRow, CatalogRunRow, RawEvidenceRow
from src.storage.service import persist_book_evidence


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES") != "1" or not os.getenv("DATABASE_URL"),
        reason="set RUN_POSTGRES=1 and DATABASE_URL to run PostgreSQL persistence test",
    ),
]

FIXTURE = Path(__file__).parents[1] / "fixtures" / "book_product.html"
URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
T0 = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def make_evidence(evidence_id: str, price: str, fetched_at: datetime) -> RawEvidence:
    body = FIXTURE.read_text(encoding="utf-8").replace("£51.77", price)
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=URL,
        fetched_at=fetched_at,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=body,
    )


def test_postgres_create_then_update_preserves_state_history_contract() -> None:
    engine = create_database_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        with session.begin():
            session.execute(delete(BookHistoryRow))
            session.execute(delete(BookRow))
            session.execute(delete(BookObservationRow))
            session.execute(delete(CatalogRunRow))
            session.execute(delete(RawEvidenceRow))

    created = persist_book_evidence(
        session_factory,
        make_evidence("pg-create", "£51.77", T0),
        changed_at=T0,
    )
    updated = persist_book_evidence(
        session_factory,
        make_evidence("pg-update", "£45.00", T0 + timedelta(days=1)),
        changed_at=T0 + timedelta(days=1),
    )

    assert created.transition.decision == StateDecision.CREATE
    assert updated.transition.decision == StateDecision.UPDATE

    with session_factory() as session:
        book = session.scalar(select(BookRow))
        history = list(session.scalars(select(BookHistoryRow).order_by(BookHistoryRow.id)))

        assert book is not None
        assert book.price == Decimal("45.00")
        assert len(history) == 2
        assert history[-1].previous_state["price"] == "51.77"
        assert history[-1].new_state["price"] == "45.00"

    engine.dispose()



def test_postgres_rolls_back_state_update_if_history_append_fails(monkeypatch) -> None:
    """INV-05: current-state update and history append are one atomic transaction.

    Raw evidence is intentionally committed before parsing/state persistence, so the
    second evidence survives the failed state transaction. The observation, current
    state update, and history append must roll back together.
    """
    engine = create_database_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        with session.begin():
            session.execute(delete(BookHistoryRow))
            session.execute(delete(BookRow))
            session.execute(delete(BookObservationRow))
            session.execute(delete(CatalogRunRow))
            session.execute(delete(RawEvidenceRow))

    persist_book_evidence(
        session_factory,
        make_evidence("pg-atomic-before", "£51.77", T0),
        changed_at=T0,
    )

    def fail_history(*args, **kwargs):
        raise RuntimeError("simulated PostgreSQL history write failure")

    monkeypatch.setattr(repositories, "_append_history", fail_history)

    with pytest.raises(RuntimeError, match="simulated PostgreSQL history write failure"):
        persist_book_evidence(
            session_factory,
            make_evidence(
                "pg-atomic-after",
                "£45.00",
                T0 + timedelta(days=1),
            ),
            changed_at=T0 + timedelta(days=1),
        )

    with session_factory() as session:
        book = session.scalar(select(BookRow))
        history = list(session.scalars(select(BookHistoryRow).order_by(BookHistoryRow.id)))
        observations = list(
            session.scalars(select(BookObservationRow).order_by(BookObservationRow.id))
        )
        evidence = list(
            session.scalars(select(RawEvidenceRow).order_by(RawEvidenceRow.fetched_at))
        )

        assert book is not None
        assert book.price == Decimal("51.77")
        assert len(history) == 1
        assert history[0].new_state["price"] == "51.77"

        # The failed update transaction must not leave a second accepted observation.
        assert len(observations) == 1
        assert observations[0].price == Decimal("51.77")

        # Raw evidence is intentionally committed in its own transaction for audit/replay.
        assert len(evidence) == 2
        assert evidence[-1].id == "pg-atomic-after"

    engine.dispose()
