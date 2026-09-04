"""Books-to-Scrape compatibility wrapper around shared product validation."""

from src.products.validation import validate_product

M0_SOURCE = "books_to_scrape"
M0_HOST = "books.toscrape.com"

validate_book = validate_product

__all__ = ["M0_SOURCE", "M0_HOST", "validate_book"]
