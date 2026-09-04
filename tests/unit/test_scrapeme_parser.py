from datetime import datetime, timezone
from pathlib import Path

from src.acquisition.models import RawEvidence
from src.scrapeme.parser import EXTRACTOR_VERSION, parse_product


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scrapeme_product.html"
URL = "https://scrapeme.live/shop/Charizard/"
T0 = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)


def test_scrapeme_raw_evidence_to_product_observation() -> None:
    evidence = RawEvidence.capture(
        evidence_id="scrapeme-charizard-001",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html; charset=UTF-8",
        body=FIXTURE.read_text(),
    )

    observation = parse_product(evidence)

    assert observation.evidence_id == evidence.id
    assert observation.extractor_version == EXTRACTOR_VERSION
    assert observation.source == "scrapeme_live"
    assert observation.source_url == URL
    assert observation.title_raw == "Charizard"
    assert observation.price_raw == "£156.00"
    assert observation.availability_raw == "31 in stock"
    assert observation.category_raw is None
