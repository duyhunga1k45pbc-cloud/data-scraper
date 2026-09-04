from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.acquisition.models import RawEvidence
from src.books.models import (
    Availability,
    BookHistoryEntry,
    BookIdentity,
    BookNormalizedData,
    BookObservation,
    Currency,
    CurrentBookState,
    StateDecision,
    StateTransitionResult,
)

from .models import BookHistoryRow, BookObservationRow, BookRow, RawEvidenceRow


class PersistenceConflictError(RuntimeError):
    pass


def _same_datetime(left: datetime, right: datetime) -> bool:
    def as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    return as_utc(left) == as_utc(right)


def persist_raw_evidence(session: Session, evidence: RawEvidence) -> RawEvidenceRow:
    existing = session.get(RawEvidenceRow, evidence.id)
    if existing is not None:
        same_evidence = (
            existing.source_url == evidence.source_url
            and _same_datetime(existing.fetched_at, evidence.fetched_at)
            and existing.status_code == evidence.status_code
            and existing.content_type == evidence.content_type
            and existing.body == evidence.body
            and existing.body_hash == evidence.body_hash
        )
        if not same_evidence:
            raise PersistenceConflictError(
                f"raw evidence id {evidence.id!r} already exists with different content"
            )
        return existing

    row = RawEvidenceRow(
        id=evidence.id,
        source_url=evidence.source_url,
        fetched_at=evidence.fetched_at,
        status_code=evidence.status_code,
        content_type=evidence.content_type,
        body=evidence.body,
        body_hash=evidence.body_hash,
    )
    session.add(row)
    session.flush()
    return row


def find_book_row(
    session: Session,
    *,
    source: str,
    canonical_product_url: str | None,
) -> BookRow | None:
    if not canonical_product_url:
        return None

    return session.scalar(
        select(BookRow).where(
            BookRow.source == source,
            BookRow.canonical_product_url == canonical_product_url,
        )
    )


def list_book_history_rows(
    session: Session,
    *,
    book_id: int,
) -> list[BookHistoryRow]:
    return list(
        session.scalars(
            select(BookHistoryRow)
            .where(BookHistoryRow.book_id == book_id)
            .order_by(BookHistoryRow.id)
        )
    )


def row_to_current_state(row: BookRow) -> CurrentBookState:
    return CurrentBookState(
        identity=BookIdentity(
            source=row.source,
            canonical_product_url=row.canonical_product_url,
        ),
        title=row.title,
        price=Decimal(row.price),
        currency=Currency(row.currency),
        availability=Availability(row.availability),
        quantity=row.quantity,
        category=row.category,
        source_url=row.source_url,
        observed_at=row.observed_at,
        updated_at=row.updated_at,
    )


def persist_book_observation(
    session: Session,
    *,
    observation: BookObservation,
    normalized: BookNormalizedData,
    transition: StateTransitionResult,
) -> BookObservationRow:
    existing = session.scalar(
        select(BookObservationRow).where(
            BookObservationRow.evidence_id == observation.evidence_id,
            BookObservationRow.extractor_version == observation.extractor_version,
        )
    )
    if existing is not None:
        return existing

    row = BookObservationRow(
        evidence_id=observation.evidence_id,
        extractor_version=observation.extractor_version,
        source=observation.source,
        source_url=observation.source_url,
        observed_at=observation.observed_at,
        title_raw=observation.title_raw,
        price_raw=observation.price_raw,
        availability_raw=observation.availability_raw,
        category_raw=observation.category_raw,
        canonical_product_url=normalized.canonical_product_url,
        title=normalized.title,
        price=normalized.price,
        currency=normalized.currency.value if normalized.currency is not None else None,
        availability=(
            normalized.availability.value if normalized.availability is not None else None
        ),
        quantity=normalized.quantity,
        category=normalized.category,
        state_decision=transition.decision.value,
        validation_errors=[error.value for error in transition.validation_errors],
    )
    session.add(row)
    session.flush()
    return row


def _state_snapshot(state: CurrentBookState) -> dict[str, object]:
    return {
        "source": state.identity.source,
        "canonical_product_url": state.identity.canonical_product_url,
        "title": state.title,
        "price": str(state.price),
        "currency": state.currency.value,
        "availability": state.availability.value,
        "quantity": state.quantity,
        "category": state.category,
        "source_url": state.source_url,
        "observed_at": state.observed_at.isoformat(),
        "updated_at": state.updated_at.isoformat(),
    }


def _create_book_row(
    session: Session,
    *,
    state: CurrentBookState,
    observation_id: int,
) -> BookRow:
    row = BookRow(
        source=state.identity.source,
        canonical_product_url=state.identity.canonical_product_url,
        title=state.title,
        price=state.price,
        currency=state.currency.value,
        availability=state.availability.value,
        quantity=state.quantity,
        category=state.category,
        source_url=state.source_url,
        observed_at=state.observed_at,
        updated_at=state.updated_at,
        accepted_observation_id=observation_id,
    )
    session.add(row)
    session.flush()
    return row


def _update_book_row(
    row: BookRow,
    *,
    state: CurrentBookState,
    observation_id: int,
) -> None:
    row.title = state.title
    row.price = state.price
    row.currency = state.currency.value
    row.availability = state.availability.value
    row.quantity = state.quantity
    row.category = state.category
    row.source_url = state.source_url
    row.observed_at = state.observed_at
    row.updated_at = state.updated_at
    row.accepted_observation_id = observation_id


def _append_history(
    session: Session,
    *,
    book_id: int,
    observation_id: int,
    history: BookHistoryEntry,
) -> BookHistoryRow:
    row = BookHistoryRow(
        book_id=book_id,
        observation_id=observation_id,
        decision=history.decision.value,
        previous_state=(
            _state_snapshot(history.previous_state)
            if history.previous_state is not None
            else None
        ),
        new_state=_state_snapshot(history.new_state),
        changed_at=history.changed_at,
    )
    session.add(row)
    session.flush()
    return row


def apply_state_transition(
    session: Session,
    *,
    existing_book: BookRow | None,
    transition: StateTransitionResult,
    observation_id: int,
) -> BookRow | None:
    if transition.decision in {StateDecision.REJECT, StateDecision.NO_CHANGE}:
        return existing_book

    if transition.current_state is None or transition.history_entry is None:
        raise ValueError("state-changing transition requires current state and history")

    if transition.decision == StateDecision.CREATE:
        if existing_book is not None:
            raise ValueError("CREATE transition cannot be applied to an existing book")
        book_row = _create_book_row(
            session,
            state=transition.current_state,
            observation_id=observation_id,
        )
        _append_history(
            session,
            book_id=book_row.id,
            observation_id=observation_id,
            history=transition.history_entry,
        )
        return book_row

    if transition.decision == StateDecision.UPDATE:
        if existing_book is None:
            raise ValueError("UPDATE transition requires an existing book")
        _update_book_row(
            existing_book,
            state=transition.current_state,
            observation_id=observation_id,
        )
        session.flush()
        _append_history(
            session,
            book_id=existing_book.id,
            observation_id=observation_id,
            history=transition.history_entry,
        )
        return existing_book

    raise ValueError(f"unsupported state decision: {transition.decision}")
