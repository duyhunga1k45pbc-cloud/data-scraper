"""Compatibility wrapper for the current ScrapeMe extractor."""

from src.extractors.scrapeme_live_v2 import (
    EXTRACTOR_VERSION,
    ProductExtractionError,
    SOURCE,
    parse_product,
)

__all__ = ["EXTRACTOR_VERSION", "ProductExtractionError", "SOURCE", "parse_product"]
