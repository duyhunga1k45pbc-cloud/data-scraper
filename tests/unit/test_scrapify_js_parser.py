from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.acquisition.models import RawEvidence
from src.products.models import Availability, Currency
from src.products.normalization import normalize_observation
from src.products.validation import validate_product
from src.scrapify_js.parser import parse_catalog


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scrapify_products.json"
URL = "https://scrapifydatalabs.com/data/products.json"
T0 = datetime(2026, 9, 5, 1, 0, tzinfo=timezone.utc)


def evidence() -> RawEvidence:
    return RawEvidence.capture(
        evidence_id="scrapify-js-fixture",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="application/json",
        body=FIXTURE.read_text(encoding="utf-8"),
    )


def test_one_json_evidence_can_produce_multiple_product_observations() -> None:
    observations = parse_catalog(evidence())

    assert len(observations) == 3
    assert {item.source_record_id_raw for item in observations} == {
        "p-1001",
        "p-1002",
        "p-1003",
    }
    assert all(item.evidence_id == "scrapify-js-fixture" for item in observations)


def test_scrapify_json_reaches_shared_validated_product_contract() -> None:
    observations = parse_catalog(evidence())
    first = normalize_observation(observations[0])
    third = normalize_observation(observations[2])

    assert first.price == Decimal("129.99")
    assert first.currency == Currency.USD
    assert first.availability == Availability.IN_STOCK
    assert first.source_record_id == "p-1001"
    assert first.canonical_product_url is None

    first_validation = validate_product(first)
    third_validation = validate_product(third)

    assert first_validation.is_valid
    assert first_validation.product is not None
    assert first_validation.product.identity.key == "id:p-1001"
    assert third_validation.is_valid
    assert third_validation.product is not None
    assert third_validation.product.availability == Availability.OUT_OF_STOCK
