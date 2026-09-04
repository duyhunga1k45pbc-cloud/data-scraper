from datetime import datetime, timezone
from pathlib import Path

from src.acquisition.models import RawEvidence
from src.scraping_sandbox.parser import parse_product


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scraping_sandbox_product.html"
URL = "https://scrapingsandbox.com/product/1"
T0 = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)


def _evidence() -> RawEvidence:
    return RawEvidence.capture(
        evidence_id="m3-sandbox-1",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=FIXTURE.read_text(encoding="utf-8"),
    )


def test_scraping_sandbox_extracts_richer_product_semantics() -> None:
    observation = parse_product(_evidence())

    assert observation.source == "scraping_sandbox"
    assert observation.source_record_id_raw == "1"
    assert observation.title_raw == "Lightweight Probiotics"
    assert observation.price_raw == "155.62"
    assert observation.compare_at_price_raw == "206.69"
    assert observation.currency_raw == "USD"
    assert observation.sku_raw == "SKU-HEA-0001"
    assert observation.categories_raw == ("Health",)
    assert len(observation.variants_raw) == 4
    assert observation.variants_raw[0].sku_raw == "SKU-HEA-0001-PIN-XXL"
    assert observation.variants_raw[0].options_raw == (("color", "Pink"), ("size", "XXL"))
    assert observation.variants_raw[2].availability_raw == "false"
