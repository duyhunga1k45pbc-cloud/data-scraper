from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from src.acquisition.models import RawEvidence
from src.storage import repositories
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import Base, BookHistoryRow, BookRow
from src.storage.service import persist_book_evidence


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


def test_state_update_rolls_back_if_history_append_fails(tmp_path, monkeypatch) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'atomic.db'}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    persist_book_evidence(
        session_factory,
        make_evidence("atomic-before", "£51.77", T0),
        changed_at=T0,
    )

    def fail_history(*args, **kwargs):
        raise RuntimeError("simulated history write failure")

    monkeypatch.setattr(repositories, "_append_history", fail_history)

    with pytest.raises(RuntimeError, match="simulated history write failure"):
        persist_book_evidence(
            session_factory,
            make_evidence(
                "atomic-after",
                "£45.00",
                T0 + timedelta(days=1),
            ),
            changed_at=T0 + timedelta(days=1),
        )

    with session_factory() as session:
        book = session.scalar(select(BookRow))
        history = list(session.scalars(select(BookHistoryRow).order_by(BookHistoryRow.id)))

        assert book is not None
        assert book.price == Decimal("51.77")
        assert len(history) == 1
        assert history[0].new_state["price"] == "51.77"

    engine.dispose()


def test_raw_evidence_id_cannot_be_reused_for_different_content(tmp_path) -> None:
    from src.storage.repositories import PersistenceConflictError

    engine = create_database_engine(f"sqlite:///{tmp_path / 'evidence-conflict.db'}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    persist_book_evidence(
        session_factory,
        make_evidence("same-id", "£51.77", T0),
        changed_at=T0,
    )

    with pytest.raises(PersistenceConflictError):
        persist_book_evidence(
            session_factory,
            make_evidence("same-id", "£45.00", T0),
            changed_at=T0,
        )

    with session_factory() as session:
        book = session.scalar(select(BookRow))
        assert book is not None
        assert book.price == Decimal("51.77")

    engine.dispose()
