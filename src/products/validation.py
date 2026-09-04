from __future__ import annotations

from urllib.parse import urlsplit

from .models import (
    Availability,
    ProductIdentity,
    ProductNormalizedData,
    ValidatedProduct,
    ValidatedProductVariant,
    ValidationErrorCode,
    ValidationResult,
)


SOURCE_HOSTS = {
    "books_to_scrape": "books.toscrape.com",
    "scrapeme_live": "scrapeme.live",
    "scrapify_js": "scrapifydatalabs.com",
    "scraping_sandbox": "scrapingsandbox.com",
}


def _canonical_url_is_valid(source: str, url: str | None) -> bool:
    expected_host = SOURCE_HOSTS.get(source)
    if expected_host is None or not url:
        return False
    parsed = urlsplit(url)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname == expected_host
        and bool(parsed.path)
    )


def _identity_is_valid(data: ProductNormalizedData) -> bool:
    if data.source_record_id:
        return True
    return _canonical_url_is_valid(data.source, data.canonical_product_url)


def validate_product(data: ProductNormalizedData) -> ValidationResult:
    errors: list[ValidationErrorCode] = []

    if not data.title or not data.title.strip():
        errors.append(ValidationErrorCode.MISSING_TITLE)

    if data.price is None:
        errors.append(ValidationErrorCode.MISSING_PRICE)
    elif data.price < 0:
        errors.append(ValidationErrorCode.NEGATIVE_PRICE)

    if data.compare_at_price is not None:
        if data.compare_at_price < 0:
            errors.append(ValidationErrorCode.NEGATIVE_COMPARE_AT_PRICE)
        elif data.price is not None and data.compare_at_price < data.price:
            errors.append(ValidationErrorCode.COMPARE_AT_BELOW_PRICE)

    if data.currency is None:
        errors.append(ValidationErrorCode.MISSING_CURRENCY)

    if data.availability is None:
        errors.append(ValidationErrorCode.UNKNOWN_AVAILABILITY)

    if data.quantity is not None and data.quantity < 0:
        errors.append(ValidationErrorCode.NEGATIVE_QUANTITY)

    if data.availability == Availability.OUT_OF_STOCK and data.quantity not in {None, 0}:
        errors.append(ValidationErrorCode.INCONSISTENT_AVAILABILITY_QUANTITY)

    if data.source not in SOURCE_HOSTS:
        errors.append(ValidationErrorCode.UNKNOWN_SOURCE)

    if not _identity_is_valid(data):
        errors.append(ValidationErrorCode.MISSING_IDENTITY)

    if (
        data.canonical_product_url is not None
        and not _canonical_url_is_valid(data.source, data.canonical_product_url)
    ):
        errors.append(ValidationErrorCode.INVALID_CANONICAL_URL)

    validated_variants: list[ValidatedProductVariant] = []
    variant_keys: set[str] = set()
    for variant in data.variants:
        if not variant.key:
            errors.append(ValidationErrorCode.MISSING_VARIANT_IDENTITY)
            continue
        if variant.key in variant_keys:
            errors.append(ValidationErrorCode.DUPLICATE_VARIANT_IDENTITY)
            continue
        variant_keys.add(variant.key)

        if variant.price is None or variant.price < 0:
            errors.append(ValidationErrorCode.INVALID_VARIANT_PRICE)
            continue
        if variant.availability is None:
            errors.append(ValidationErrorCode.INVALID_VARIANT_AVAILABILITY)
            continue

        validated_variants.append(
            ValidatedProductVariant(
                key=variant.key,
                sku=variant.sku,
                options=variant.options,
                price=variant.price,
                availability=variant.availability,
            )
        )

    if errors:
        return ValidationResult(product=None, errors=tuple(errors))

    assert data.title is not None
    assert data.price is not None
    assert data.currency is not None
    assert data.availability is not None

    identity = ProductIdentity(
        source=data.source,
        canonical_product_url=data.canonical_product_url,
        source_record_id=data.source_record_id,
    )

    return ValidationResult(
        product=ValidatedProduct(
            identity=identity,
            title=data.title,
            price=data.price,
            compare_at_price=data.compare_at_price,
            currency=data.currency,
            availability=data.availability,
            quantity=data.quantity,
            category=data.category,
            sku=data.sku,
            categories=data.categories,
            variants=tuple(validated_variants),
            source_url=(data.source_url or data.canonical_product_url or ""),
            observed_at=data.observed_at,
        ),
        errors=(),
    )
