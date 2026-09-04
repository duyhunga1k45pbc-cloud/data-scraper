import os

import httpx
import pytest
from bs4 import BeautifulSoup

from src.acquisition.fetch import fetch_url
from src.scrapify_js.parser import parse_catalog
from src.scrapify_js.service import DATA_URL, STOREFRONT_URL, fetch_catalog_evidence


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE") != "1",
        reason="set RUN_LIVE=1 to run live source tests",
    ),
]


def test_m2_static_http_cannot_see_js_rendered_product_cards() -> None:
    evidence = fetch_url(STOREFRONT_URL)
    soup = BeautifulSoup(evidence.body, "lxml")

    assert evidence.status_code == 200
    assert soup.select(".product-card") == []
    assert soup.select_one("#js-product-list") is not None


def test_m2_public_network_data_is_preferred_over_browser_automation() -> None:
    evidence = fetch_catalog_evidence()
    observations = parse_catalog(evidence)

    assert evidence.source_url == DATA_URL
    assert evidence.status_code == 200
    assert "json" in evidence.content_type.lower()
    assert len(observations) >= 10
    assert all(item.source_record_id_raw for item in observations)
