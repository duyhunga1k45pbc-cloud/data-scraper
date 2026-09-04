from __future__ import annotations

import os

import pytest

from src.browser_acquisition.probe import probe_js_link_discovery

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER") != "1" or os.getenv("RUN_LIVE") != "1",
    reason="set RUN_BROWSER=1 and RUN_LIVE=1 for the opt-in safe live browser proof",
)


def test_m18_live_web_scraping_dev_js_only_links():
    # web-scraping.dev explicitly describes itself as a safe/legal learning fixture.
    result = probe_js_link_discovery(
        "https://web-scraping.dev/js-links",
        timeout_ms=20_000,
        settle_ms=750,
    )

    assert result.status_code == 200
    assert len(result.rendered_hrefs) > len(result.initial_hrefs)
    assert result.js_added_links is True
