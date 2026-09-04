"""Compatibility wrapper for the current Books to Scrape extractor."""

from src.extractors.books_to_scrape_v1 import (
    BookExtractionError,
    EXTRACTOR_VERSION,
    SOURCE,
    parse_book,
)

__all__ = ["BookExtractionError", "EXTRACTOR_VERSION", "SOURCE", "parse_book"]
