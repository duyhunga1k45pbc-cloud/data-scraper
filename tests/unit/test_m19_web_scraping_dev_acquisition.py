from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.catalogs.models import CatalogChunkStatus, CatalogRunStatus
from src.web_scraping_dev.acquisition import (
    HttpPageLoadError,
    HttpPageSnapshot,
    acquire_web_scraping_dev_catalog,
)

T0 = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
CAT1 = """<html><body>
<a href="/product/1">p1</a><a href="/products?page=2">next</a>
</body></html>"""
CAT2 = """<html><body>
<a href="/product/1">duplicate p1</a><a href="/product/2">p2</a>
</body></html>"""
DETAIL = """<html><body>
<h3 class="product-title">Fixture Product</h3>
<span class="product-price">$10.00</span>
<span class="product-price-full">$12.00</span>
<span class="stock-status" data-available="true"></span>
</body></html>"""


def snap(ref: str, body: str, second: int) -> HttpPageSnapshot:
    return HttpPageSnapshot(
        requested_ref=ref,
        attempted_at=T0 + timedelta(seconds=second),
        final_url=ref,
        status_code=200,
        content_type="text/html",
        body=body,
    )


def pages():
    return {
        "https://web-scraping.dev/products?page=1": snap("https://web-scraping.dev/products?page=1", CAT1, 0),
        "https://web-scraping.dev/products?page=2": snap("https://web-scraping.dev/products?page=2", CAT2, 1),
        "https://web-scraping.dev/product/1": snap("https://web-scraping.dev/product/1", DETAIL, 2),
        "https://web-scraping.dev/product/2": snap("https://web-scraping.dev/product/2", DETAIL, 3),
    }


def test_m19_pagination_overlap_dedup_and_detail_chain_proves_complete():
    acquisition = acquire_web_scraping_dev_catalog(
        load_page=pages().__getitem__, run_key="m19-complete-fixture"
    )
    assert acquisition.coverage_status == CatalogRunStatus.COMPLETE
    assert len(acquisition.observations) == 2
    assert [chunk.status for chunk in acquisition.chunks] == [
        CatalogChunkStatus.SUCCESS,
        CatalogChunkStatus.SUCCESS,
        CatalogChunkStatus.SUCCESS,
        CatalogChunkStatus.SUCCESS,
    ]
    assert acquisition.chunks[-1].next_ref is None


def test_m19_detail_failure_keeps_prior_observation_but_never_proves_absence():
    fixture = pages()

    def loader(ref: str):
        if ref == "https://web-scraping.dev/product/2":
            raise HttpPageLoadError("HTTP_TIMEOUT")
        return fixture[ref]

    acquisition = acquire_web_scraping_dev_catalog(
        load_page=loader, run_key="m19-detail-failure-fixture"
    )
    assert acquisition.coverage_status == CatalogRunStatus.INCOMPLETE
    assert len(acquisition.observations) == 1
    assert acquisition.chunks[-1].status == CatalogChunkStatus.FETCH_FAILED


def test_m19_product_limit_is_explicit_incomplete_not_truncated_complete():
    acquisition = acquire_web_scraping_dev_catalog(
        load_page=pages().__getitem__, max_products=1, run_key="m19-limit-fixture"
    )
    assert acquisition.coverage_status == CatalogRunStatus.INCOMPLETE
    assert len(acquisition.observations) == 1
    assert acquisition.chunks[-1].status == CatalogChunkStatus.LIMIT_REACHED
    assert acquisition.chunks[-1].requested_ref == "https://web-scraping.dev/product/2"
