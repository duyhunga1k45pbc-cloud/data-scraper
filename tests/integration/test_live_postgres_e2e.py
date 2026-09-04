from __future__ import annotations

import os

import pytest
from sqlalchemy import delete, select

from src.books.models import StateDecision
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import (
    Base,
    BookHistoryRow,
    BookObservationRow,
    BookRow,
    CatalogRunRow,
    RawEvidenceRow,
)
from src.storage.service import persist_book_url


URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"

pytestmark = [
    pytest.mark.live,
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE") != "1"
        or os.getenv("RUN_POSTGRES") != "1"
        or not os.getenv("DATABASE_URL"),
        reason=(
            "set RUN_LIVE=1, RUN_POSTGRES=1 and DATABASE_URL to run the "
            "live PostgreSQL end-to-end test"
        ),
    ),
]


def test_live_book_is_traceable_from_source_to_postgres_state_and_history() -> None:
    """Prove the M0 chain against the live source and real PostgreSQL.

    External source -> RawEvidence -> Observation -> Normalize -> Validate ->
    State Decision -> Current State -> History.
    """
    engine = create_database_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    try:
        with session_factory() as session:
            with session.begin():
                session.execute(delete(BookHistoryRow))
                session.execute(delete(BookRow))
                session.execute(delete(BookObservationRow))
                session.execute(delete(CatalogRunRow))
            session.execute(delete(RawEvidenceRow))

        result = persist_book_url(session_factory, URL)

        assert result.evidence.status_code == 200
        assert "text/html" in result.evidence.content_type.lower()
        assert result.evidence.body
        assert result.observation.evidence_id == result.evidence.id
        assert result.transition.decision == StateDecision.CREATE
        assert result.transition.current_state is not None
        assert result.book_id is not None

        with session_factory() as session:
            evidence_row = session.get(RawEvidenceRow, result.evidence.id)
            observation_row = session.get(BookObservationRow, result.observation_id)
            book_row = session.get(BookRow, result.book_id)
            history = list(
                session.scalars(
                    select(BookHistoryRow)
                    .where(BookHistoryRow.book_id == result.book_id)
                    .order_by(BookHistoryRow.id)
                )
            )

            assert evidence_row is not None
            assert evidence_row.source_url == URL
            assert evidence_row.body == result.evidence.body
            assert evidence_row.body_hash == result.evidence.body_hash

            assert observation_row is not None
            assert observation_row.evidence_id == evidence_row.id
            assert observation_row.state_decision == StateDecision.CREATE.value
            assert observation_row.title == result.normalized.title
            assert observation_row.price == result.normalized.price

            assert book_row is not None
            assert book_row.accepted_observation_id == observation_row.id
            assert book_row.canonical_product_url == result.normalized.canonical_product_url
            assert book_row.title == result.transition.current_state.title
            assert book_row.price == result.transition.current_state.price
            assert book_row.currency == result.transition.current_state.currency.value
            assert book_row.availability == result.transition.current_state.availability.value

            assert len(history) == 1
            assert history[0].observation_id == observation_row.id
            assert history[0].decision == StateDecision.CREATE.value
            assert history[0].previous_state is None
            assert history[0].new_state["title"] == book_row.title
            assert history[0].new_state["price"] == str(book_row.price)
    finally:
        engine.dispose()
