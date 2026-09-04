from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from src.products.models import (
    Availability,
    Currency,
    ProductNormalizedData,
    ProductVariantNormalizedData,
    ValidationErrorCode,
)
from src.products.validation import validate_product


T0 = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)


def _base() -> ProductNormalizedData:
    return ProductNormalizedData(
        source="scraping_sandbox",
        source_url="https://scrapingsandbox.com/product/1",
        canonical_product_url="https://scrapingsandbox.com/product/1",
        source_record_id="1",
        observed_at=T0,
        title="Lightweight Probiotics",
        price=Decimal("155.62"),
        compare_at_price=Decimal("206.69"),
        currency=Currency.USD,
        availability=Availability.IN_STOCK,
        quantity=None,
        category="Health",
        sku="SKU-HEA-0001",
        categories=("Health",),
        variants=(
            ProductVariantNormalizedData(
                key="sku:SKU-HEA-0001-PIN-XXL",
                sku="SKU-HEA-0001-PIN-XXL",
                options=(("color", "Pink"), ("size", "XXL")),
                price=Decimal("153.43"),
                availability=Availability.IN_STOCK,
            ),
        ),
    )


def test_compare_at_price_cannot_be_below_current_price() -> None:
    result = validate_product(replace(_base(), compare_at_price=Decimal("100.00")))
    assert not result.is_valid
    assert ValidationErrorCode.COMPARE_AT_BELOW_PRICE in result.errors


def test_duplicate_variant_identity_is_rejected() -> None:
    base = _base()
    result = validate_product(replace(base, variants=(base.variants[0], base.variants[0])))
    assert not result.is_valid
    assert ValidationErrorCode.DUPLICATE_VARIANT_IDENTITY in result.errors
