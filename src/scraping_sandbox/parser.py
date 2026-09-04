"""Compatibility wrapper for the current ScrapingSandbox extractor."""

from src.extractors.scraping_sandbox_json_v1 import (
    EXTRACTOR_VERSION,
    SOURCE,
    ScrapingSandboxExtractionError,
    parse_product,
)

__all__ = [
    "EXTRACTOR_VERSION",
    "SOURCE",
    "ScrapingSandboxExtractionError",
    "parse_product",
]
