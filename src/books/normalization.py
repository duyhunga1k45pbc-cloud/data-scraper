"""Books-to-Scrape compatibility wrapper around shared product normalization."""

from src.products.normalization import canonicalize_product_url, normalize_observation

__all__ = ["canonicalize_product_url", "normalize_observation"]
