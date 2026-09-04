from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.books.models import (
    Availability,
    BookNormalizedData,
    Currency,
    StateDecision,
    ValidationErrorCode,
)
from src.books.state import process_normalized_book


T0 = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"


def book_data(
    *,
    price: Decimal | None = Decimal("51.77"),
    observed_at: datetime = T0,
) -> BookNormalizedData:
    return BookNormalizedData(
        source="books_to_scrape",
        canonical_product_url=URL,
        observed_at=observed_at,
        title="A Light in the Attic",
        price=price,
        currency=Currency.GBP if price is not None else None,
        availability=Availability.IN_STOCK,
        quantity=22,
        category="Poetry",
    )


def test_ac01_valid_new_book_creates_current_state_and_initial_history() -> None:
    result = process_normalized_book(None, book_data(), changed_at=T0)

    assert result.decision == StateDecision.CREATE
    assert result.current_state is not None
    assert result.current_state.price == Decimal("51.77")
    assert result.history_entry is not None
    assert result.history_entry.previous_state is None
    assert result.history_entry.new_state == result.current_state


def test_ac02_same_valid_state_is_idempotent() -> None:
    created = process_normalized_book(None, book_data(), changed_at=T0)
    current = created.current_state
    assert current is not None

    result = process_normalized_book(
        current,
        book_data(observed_at=T0 + timedelta(days=1)),
        changed_at=T0 + timedelta(days=1),
    )

    assert result.decision == StateDecision.NO_CHANGE
    assert result.current_state == current
    assert result.history_entry is None


def test_ac03_negative_price_is_rejected_without_state_or_history_change() -> None:
    created = process_normalized_book(None, book_data(), changed_at=T0)
    current = created.current_state
    assert current is not None

    result = process_normalized_book(
        current,
        book_data(price=Decimal("-10"), observed_at=T0 + timedelta(days=1)),
        changed_at=T0 + timedelta(days=1),
    )

    assert result.decision == StateDecision.REJECT
    assert ValidationErrorCode.NEGATIVE_PRICE in result.validation_errors
    assert result.current_state == current
    assert result.history_entry is None


def test_ac04_missing_required_price_is_rejected_without_state_change() -> None:
    created = process_normalized_book(None, book_data(), changed_at=T0)
    current = created.current_state
    assert current is not None

    result = process_normalized_book(
        current,
        book_data(price=None, observed_at=T0 + timedelta(days=1)),
        changed_at=T0 + timedelta(days=1),
    )

    assert result.decision == StateDecision.REJECT
    assert ValidationErrorCode.MISSING_PRICE in result.validation_errors
    assert result.current_state == current
    assert result.history_entry is None


def test_ac05_valid_price_change_updates_state_and_appends_one_history_transition() -> None:
    created = process_normalized_book(None, book_data(), changed_at=T0)
    current = created.current_state
    assert current is not None

    result = process_normalized_book(
        current,
        book_data(price=Decimal("45.00"), observed_at=T0 + timedelta(days=1)),
        changed_at=T0 + timedelta(days=1),
    )

    assert result.decision == StateDecision.UPDATE
    assert result.current_state is not None
    assert result.current_state.price == Decimal("45.00")
    assert result.history_entry is not None
    assert result.history_entry.previous_state == current
    assert result.history_entry.new_state == result.current_state
