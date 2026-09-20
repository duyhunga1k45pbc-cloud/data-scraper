from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal

from src.acquisition.models import RawEvidence
from src.products.models import StateDecision
from src.products.normalization import normalize_observation
from src.products.state import process_normalized_product
from src.web_scraping_dev.parser import EXTRACTOR_VERSION, SOURCE, parse_product_evidence

T0 = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
HTML = """<!doctype html><html><body>
<h3 class="product-title">Box of Chocolate Candy</h3>
<span class="product-price">$9.99</span>
<span class="product-price-full">$12.99</span>
<div class="variant-options">
  <div class="variant"><span class="stock-status" data-available="false"></span></div>
  <div class="variant"><span class="stock-status" data-available="true"></span></div>
</div>
</body></html>"""


def evidence(product_id: int = 1) -> RawEvidence:
    digest = hashlib.sha256(HTML.encode()).hexdigest()
    return RawEvidence(
        id=f"m19-{product_id}",
        source_url=f"https://web-scraping.dev/product/{product_id}",
        fetched_at=T0,
        status_code=200,
        content_type="text/html",
        body=HTML,
        body_hash=digest,
    )


def test_m19_real_source_parser_enters_existing_product_pipeline_without_new_state_logic():
    observation = parse_product_evidence(evidence())[0]
    assert observation.source == SOURCE
    assert observation.extractor_version == EXTRACTOR_VERSION

    normalized = normalize_observation(observation)
    result = process_normalized_product(None, normalized, changed_at=T0)

    assert result.decision == StateDecision.CREATE
    assert result.current_state is not None
    assert result.current_state.identity.source == SOURCE
    assert result.current_state.identity.source_record_id == "1"
    assert result.current_state.price == Decimal("9.99")
    assert result.current_state.compare_at_price == Decimal("12.99")
