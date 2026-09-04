from src.extractors.registry import (
    ExtractorRuntimeNotFoundError,
    list_extractor_runtimes,
    resolve_extractor_runtime,
)


def test_m11_current_extractors_are_version_addressable() -> None:
    runtimes = {(item.source, item.version): item for item in list_extractor_runtimes()}

    assert runtimes[("books_to_scrape", "books-to-scrape-v1")].implementation == (
        "src.extractors.books_to_scrape_v1:parse_book"
    )
    assert runtimes[("scrapeme_live", "scrapeme-live-v2")].implementation == (
        "src.extractors.scrapeme_live_v2:parse_product"
    )
    assert runtimes[("scrapify_js", "scrapify-js-json-v1")].implementation == (
        "src.extractors.scrapify_js_json_v1:parse_catalog"
    )
    assert runtimes[("scraping_sandbox", "scraping-sandbox-json-v1")].implementation == (
        "src.extractors.scraping_sandbox_json_v1:parse_product"
    )


def test_m11_unknown_historical_version_is_not_silently_replaced_by_latest() -> None:
    try:
        resolve_extractor_runtime(source="books_to_scrape", version="books-to-scrape-v999")
    except ExtractorRuntimeNotFoundError as exc:
        assert "books-to-scrape-v999" in str(exc)
    else:
        raise AssertionError("unknown version must not fall back to the latest parser")
