from __future__ import annotations

from datetime import datetime, timezone

from .models import (
    BookHistoryEntry,
    BookNormalizedData,
    CurrentBookState,
    StateDecision,
    StateTransitionResult,
    ValidatedBook,
)
from .validation import validate_book


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_current_state(book: ValidatedBook, *, updated_at: datetime) -> CurrentBookState:
    return CurrentBookState(
        identity=book.identity,
        title=book.title,
        price=book.price,
        currency=book.currency,
        availability=book.availability,
        quantity=book.quantity,
        category=book.category,
        source_url=book.source_url,
        observed_at=book.observed_at,
        updated_at=updated_at,
    )


def _same_business_state(current: CurrentBookState, incoming: ValidatedBook) -> bool:
    return (
        current.identity == incoming.identity
        and current.title == incoming.title
        and current.price == incoming.price
        and current.currency == incoming.currency
        and current.availability == incoming.availability
        and current.quantity == incoming.quantity
        and current.category == incoming.category
        and current.source_url == incoming.source_url
    )


def transition_validated_book(
    current: CurrentBookState | None,
    incoming: ValidatedBook,
    *,
    changed_at: datetime | None = None,
) -> StateTransitionResult:
    changed_at = changed_at or _utc_now()

    if current is None:
        new_state = _as_current_state(incoming, updated_at=changed_at)
        history = BookHistoryEntry(
            identity=incoming.identity,
            decision=StateDecision.CREATE,
            previous_state=None,
            new_state=new_state,
            changed_at=changed_at,
        )
        return StateTransitionResult(
            decision=StateDecision.CREATE,
            current_state=new_state,
            history_entry=history,
        )

    if current.identity != incoming.identity:
        raise ValueError("incoming book identity does not match current state identity")

    if _same_business_state(current, incoming):
        return StateTransitionResult(
            decision=StateDecision.NO_CHANGE,
            current_state=current,
            history_entry=None,
        )

    new_state = _as_current_state(incoming, updated_at=changed_at)
    history = BookHistoryEntry(
        identity=incoming.identity,
        decision=StateDecision.UPDATE,
        previous_state=current,
        new_state=new_state,
        changed_at=changed_at,
    )
    return StateTransitionResult(
        decision=StateDecision.UPDATE,
        current_state=new_state,
        history_entry=history,
    )


def process_normalized_book(
    current: CurrentBookState | None,
    data: BookNormalizedData,
    *,
    changed_at: datetime | None = None,
) -> StateTransitionResult:
    validation = validate_book(data)

    if not validation.is_valid:
        return StateTransitionResult(
            decision=StateDecision.REJECT,
            current_state=current,
            history_entry=None,
            validation_errors=validation.errors,
        )

    assert validation.book is not None
    return transition_validated_book(
        current,
        validation.book,
        changed_at=changed_at,
    )
