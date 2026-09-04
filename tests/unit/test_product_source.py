import pytest

from src.products.source import UnsupportedSourceError, source_for_url


def test_source_for_url_supports_both_m1_product_sources() -> None:
    assert source_for_url(
        "https://books.toscrape.com/catalogue/example_1/index.html"
    ) == "books_to_scrape"
    assert source_for_url("https://scrapeme.live/shop/Charizard/") == "scrapeme_live"


def test_source_for_url_rejects_unknown_hosts_before_fetch() -> None:
    with pytest.raises(UnsupportedSourceError):
        source_for_url("https://example.com/product/1")
