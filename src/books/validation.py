from __future__ import annotations

from urllib.parse import urlsplit

from .models import (
    Availability,
    BookIdentity,
    BookNormalizedData,
    ValidatedBook,
    ValidationErrorCode,
    ValidationResult,
)


M0_SOURCE = "books_to_scrape"
M0_HOST = "books.toscrape.com"


def _canonical_url_is_valid(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlsplit(url)
    return parsed.scheme in {"http", "https"} and parsed.hostname == M0_HOST and bool(parsed.path)


def validate_book(data: BookNormalizedData) -> ValidationResult:
    errors: list[ValidationErrorCode] = []

    if not data.title or not data.title.strip():
        errors.append(ValidationErrorCode.MISSING_TITLE)

    if data.price is None:
        errors.append(ValidationErrorCode.MISSING_PRICE)
    elif data.price < 0:
        errors.append(ValidationErrorCode.NEGATIVE_PRICE)

    if data.currency is None:
        errors.append(ValidationErrorCode.MISSING_CURRENCY)

    if data.availability is None:
        errors.append(ValidationErrorCode.UNKNOWN_AVAILABILITY)

    if data.quantity is not None and data.quantity < 0:
        errors.append(ValidationErrorCode.NEGATIVE_QUANTITY)

    if data.availability == Availability.OUT_OF_STOCK and data.quantity not in {None, 0}:
        errors.append(ValidationErrorCode.INCONSISTENT_AVAILABILITY_QUANTITY)

    if data.source != M0_SOURCE:
        errors.append(ValidationErrorCode.UNKNOWN_SOURCE)

    if not _canonical_url_is_valid(data.canonical_product_url):
        errors.append(ValidationErrorCode.INVALID_CANONICAL_URL)

    if errors:
        return ValidationResult(book=None, errors=tuple(errors))

    assert data.title is not None
    assert data.price is not None
    assert data.currency is not None
    assert data.availability is not None
    assert data.canonical_product_url is not None

    identity = BookIdentity(
        source=data.source,
        canonical_product_url=data.canonical_product_url,
    )

    return ValidationResult(
        book=ValidatedBook(
            identity=identity,
            title=data.title,
            price=data.price,
            currency=data.currency,
            availability=data.availability,
            quantity=data.quantity,
            category=data.category,
            source_url=data.canonical_product_url,
            observed_at=data.observed_at,
        ),
        errors=(),
    )
