from __future__ import annotations

import os

import pytest

from src.products.models import StateDecision
from src.products.normalization import normalize_observation
from src.products.state import process_normalized_product
from src.web_scraping_dev.acquisition import HttpxPageLoader, discover_catalog_page, raw_evidence_from_snapshot
from src.web_scraping_dev.parser import SOURCE, parse_product_evidence

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE") != "1",
    reason="set RUN_LIVE=1 for the opt-in safe live web-scraping.dev proof",
)


def test_m19_live_catalog_discovery_and_product_detail_use_existing_pipeline():
    loader = HttpxPageLoader(timeout_seconds=20)
    catalog = loader("https://web-scraping.dev/products?page=1")
    assert catalog.status_code == 200
    discovery = discover_catalog_page(catalog.body or "", catalog.final_url or catalog.requested_ref)
    assert discovery.product_urls
    assert discovery.next_catalog_url is not None

    detail = loader(discovery.product_urls[0])
    assert detail.status_code == 200
    evidence = raw_evidence_from_snapshot(detail)
    assert evidence is not None
    observation = parse_product_evidence(evidence)[0]
    normalized = normalize_observation(observation)
    transition = process_normalized_product(None, normalized, changed_at=detail.attempted_at)

    assert observation.source == SOURCE
    assert transition.decision == StateDecision.CREATE
    assert transition.current_state is not None
