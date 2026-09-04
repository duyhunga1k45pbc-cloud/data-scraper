from datetime import datetime, timezone
from decimal import Decimal

from src.books.models import Availability, BookNormalizedData, Currency, ValidationErrorCode
from src.books.validation import validate_book


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
URL = "https://books.toscrape.com/catalogue/example_1/index.html"


def normalized(**overrides) -> BookNormalizedData:
    values = {
        "source": "books_to_scrape",
        "canonical_product_url": URL,
        "observed_at": NOW,
        "title": "Example",
        "price": Decimal("10.00"),
        "currency": Currency.GBP,
        "availability": Availability.IN_STOCK,
        "quantity": 2,
        "category": "Books",
    }
    values.update(overrides)
    return BookNormalizedData(**values)


def test_out_of_stock_with_positive_quantity_is_inconsistent() -> None:
    result = validate_book(
        normalized(availability=Availability.OUT_OF_STOCK, quantity=2)
    )

    assert not result.is_valid
    assert ValidationErrorCode.INCONSISTENT_AVAILABILITY_QUANTITY in result.errors


def test_unknown_source_is_rejected() -> None:
    result = validate_book(normalized(source="other_source"))

    assert not result.is_valid
    assert ValidationErrorCode.UNKNOWN_SOURCE in result.errors
