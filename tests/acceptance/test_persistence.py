from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from src.acquisition.models import RawEvidence
from src.books.models import StateDecision, ValidationErrorCode
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import Base, BookHistoryRow, BookObservationRow, BookRow, RawEvidenceRow
from src.storage.service import persist_book_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "book_product.html"
URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
T0 = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'm0.db'}")
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def evidence(
    evidence_id: str,
    *,
    price: str = "£51.77",
    fetched_at: datetime = T0,
) -> RawEvidence:
    body = FIXTURE.read_text(encoding="utf-8").replace("£51.77", price)
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=URL,
        fetched_at=fetched_at,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=body,
    )


def count_rows(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_p01_create_persists_evidence_observation_state_and_initial_history(
    session_factory,
) -> None:
    result = persist_book_evidence(
        session_factory,
        evidence("evidence-create"),
        changed_at=T0,
    )

    assert result.transition.decision == StateDecision.CREATE

    with session_factory() as session:
        assert count_rows(session, RawEvidenceRow) == 1
        assert count_rows(session, BookObservationRow) == 1
        assert count_rows(session, BookRow) == 1
        assert count_rows(session, BookHistoryRow) == 1

        book = session.scalar(select(BookRow))
        observation = session.scalar(select(BookObservationRow))
        history = session.scalar(select(BookHistoryRow))

        assert book is not None
        assert observation is not None
        assert history is not None
        assert book.price == Decimal("51.77")
        assert book.accepted_observation_id == observation.id
        assert observation.state_decision == StateDecision.CREATE.value
        assert observation.validation_errors == []
        assert history.observation_id == observation.id
        assert history.previous_state is None
        assert history.new_state["price"] == "51.77"


def test_p02_same_effective_state_does_not_append_history(session_factory) -> None:
    persist_book_evidence(
        session_factory,
        evidence("evidence-first"),
        changed_at=T0,
    )

    second = persist_book_evidence(
        session_factory,
        evidence("evidence-second", fetched_at=T0 + timedelta(days=1)),
        changed_at=T0 + timedelta(days=1),
    )

    assert second.transition.decision == StateDecision.NO_CHANGE

    with session_factory() as session:
        assert count_rows(session, RawEvidenceRow) == 2
        assert count_rows(session, BookObservationRow) == 2
        assert count_rows(session, BookRow) == 1
        assert count_rows(session, BookHistoryRow) == 1

        decisions = list(
            session.scalars(select(BookObservationRow.state_decision).order_by(BookObservationRow.id))
        )
        assert decisions == [StateDecision.CREATE.value, StateDecision.NO_CHANGE.value]


def test_p03_valid_change_updates_current_state_and_appends_history(session_factory) -> None:
    first = persist_book_evidence(
        session_factory,
        evidence("evidence-before"),
        changed_at=T0,
    )

    second = persist_book_evidence(
        session_factory,
        evidence(
            "evidence-after",
            price="£45.00",
            fetched_at=T0 + timedelta(days=1),
        ),
        changed_at=T0 + timedelta(days=1),
    )

    assert first.transition.decision == StateDecision.CREATE
    assert second.transition.decision == StateDecision.UPDATE

    with session_factory() as session:
        book = session.scalar(select(BookRow))
        history = list(session.scalars(select(BookHistoryRow).order_by(BookHistoryRow.id)))
        observations = list(
            session.scalars(select(BookObservationRow).order_by(BookObservationRow.id))
        )

        assert book is not None
        assert book.price == Decimal("45.00")
        assert len(history) == 2
        assert history[-1].decision == StateDecision.UPDATE.value
        assert history[-1].previous_state["price"] == "51.77"
        assert history[-1].new_state["price"] == "45.00"
        assert book.accepted_observation_id == observations[-1].id


def test_p04_invalid_data_is_traced_but_cannot_mutate_state_or_history(
    session_factory,
) -> None:
    persist_book_evidence(
        session_factory,
        evidence("evidence-valid"),
        changed_at=T0,
    )

    rejected = persist_book_evidence(
        session_factory,
        evidence(
            "evidence-invalid",
            price="-£10.00",
            fetched_at=T0 + timedelta(days=1),
        ),
        changed_at=T0 + timedelta(days=1),
    )

    assert rejected.transition.decision == StateDecision.REJECT
    assert ValidationErrorCode.NEGATIVE_PRICE in rejected.transition.validation_errors

    with session_factory() as session:
        book = session.scalar(select(BookRow))
        observations = list(
            session.scalars(select(BookObservationRow).order_by(BookObservationRow.id))
        )

        assert book is not None
        assert book.price == Decimal("51.77")
        assert count_rows(session, BookHistoryRow) == 1
        assert len(observations) == 2
        assert observations[-1].state_decision == StateDecision.REJECT.value
        assert observations[-1].validation_errors == [
            ValidationErrorCode.NEGATIVE_PRICE.value
        ]
        assert observations[-1].price == Decimal("-10.00")


def test_p05_reprocessing_same_evidence_does_not_duplicate_business_effects(
    session_factory,
) -> None:
    same_evidence = evidence("evidence-idempotent")

    first = persist_book_evidence(session_factory, same_evidence, changed_at=T0)
    second = persist_book_evidence(session_factory, same_evidence, changed_at=T0)

    assert first.transition.decision == StateDecision.CREATE
    assert second.transition.decision == StateDecision.NO_CHANGE

    with session_factory() as session:
        assert count_rows(session, RawEvidenceRow) == 1
        assert count_rows(session, BookObservationRow) == 1
        assert count_rows(session, BookRow) == 1
        assert count_rows(session, BookHistoryRow) == 1


def test_p06_raw_evidence_survives_extraction_failure(session_factory) -> None:
    broken = RawEvidence.capture(
        evidence_id="evidence-broken-html",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body="<html><body>not a product page</body></html>",
    )

    from src.books.parser import BookExtractionError

    with pytest.raises(BookExtractionError, match="PRODUCT_MAIN_NOT_FOUND"):
        persist_book_evidence(session_factory, broken, changed_at=T0)

    with session_factory() as session:
        assert count_rows(session, RawEvidenceRow) == 1
        assert count_rows(session, BookObservationRow) == 0
        assert count_rows(session, BookRow) == 0
        assert count_rows(session, BookHistoryRow) == 0
