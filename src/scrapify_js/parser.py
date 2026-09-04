"""Compatibility wrapper for the current Scrapify JSON extractor."""

from src.extractors.scrapify_js_json_v1 import (
    EXTRACTOR_VERSION,
    SOURCE,
    ScrapifyCatalogExtractionError,
    parse_catalog,
)

__all__ = [
    "EXTRACTOR_VERSION",
    "SOURCE",
    "ScrapifyCatalogExtractionError",
    "parse_catalog",
]
