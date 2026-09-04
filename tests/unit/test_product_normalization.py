from datetime import datetime, timezone
from decimal import Decimal

from src.products.models import Availability, Currency, ProductObservation
from src.products.normalization import normalize_observation


T0 = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)


def test_scrapeme_availability_normalizes_into_shared_product_contract() -> None:
    observation = ProductObservation(
        evidence_id="ev-1",
        extractor_version="scrapeme-live-v1",
        source="scrapeme_live",
        source_url="https://scrapeme.live/shop/Charizard/",
        observed_at=T0,
        title_raw="Charizard",
        price_raw="£156.00",
        availability_raw="31 in stock",
        category_raw=None,
    )

    normalized = normalize_observation(observation)

    assert normalized.price == Decimal("156.00")
    assert normalized.currency == Currency.GBP
    assert normalized.availability == Availability.IN_STOCK
    assert normalized.quantity == 31
    assert normalized.canonical_product_url == "https://scrapeme.live/shop/Charizard/"
