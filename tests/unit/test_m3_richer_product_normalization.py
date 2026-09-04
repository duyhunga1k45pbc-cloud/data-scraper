from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.acquisition.models import RawEvidence
from src.products.models import Availability, Currency
from src.products.normalization import normalize_observation
from src.scraping_sandbox.parser import parse_product


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scraping_sandbox_product.html"
URL = "https://scrapingsandbox.com/product/1"
T0 = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)


def test_m3_normalizes_compare_price_sku_categories_and_variants() -> None:
    evidence = RawEvidence.capture(
        evidence_id="m3-normalize",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html",
        body=FIXTURE.read_text(encoding="utf-8"),
    )
    normalized = normalize_observation(parse_product(evidence))

    assert normalized.source_record_id == "1"
    assert normalized.canonical_product_url == URL
    assert normalized.price == Decimal("155.62")
    assert normalized.compare_at_price == Decimal("206.69")
    assert normalized.currency == Currency.USD
    assert normalized.sku == "SKU-HEA-0001"
    assert normalized.categories == ("Health",)
    assert len(normalized.variants) == 4
    assert normalized.variants[0].key == "sku:SKU-HEA-0001-PIN-XXL"
    assert normalized.variants[0].price == Decimal("153.43")
    assert normalized.variants[0].availability == Availability.IN_STOCK
    assert normalized.variants[2].availability == Availability.OUT_OF_STOCK
