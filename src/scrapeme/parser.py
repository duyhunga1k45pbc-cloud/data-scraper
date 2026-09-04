from __future__ import annotations

from bs4 import BeautifulSoup

from src.acquisition.models import RawEvidence
from src.products.models import ProductObservation


EXTRACTOR_VERSION = "scrapeme-live-v1"
SOURCE = "scrapeme_live"


class ProductExtractionError(ValueError):
    pass


def _text_or_none(node) -> str | None:
    if node is None:
        return None
    text = node.get_text(" ", strip=True)
    return text or None


def parse_product(evidence: RawEvidence) -> ProductObservation:
    soup = BeautifulSoup(evidence.body, "lxml")

    summary = soup.select_one("div.summary.entry-summary")
    if summary is None:
        summary = soup.select_one("div.summary")
    if summary is None:
        raise ProductExtractionError("PRODUCT_SUMMARY_NOT_FOUND")

    title = summary.select_one("h1.product_title") or summary.select_one("h1")
    price = summary.select_one("p.price")
    stock = summary.select_one("p.stock")

    # WooCommerce exposes multiple categories here while the M0 contract has
    # one optional category field. M1 does not invent a primary category; leave
    # it unset until a real requirement justifies category-cardinality changes.

    return ProductObservation(
        evidence_id=evidence.id,
        extractor_version=EXTRACTOR_VERSION,
        source=SOURCE,
        source_url=evidence.source_url,
        observed_at=evidence.fetched_at,
        title_raw=_text_or_none(title),
        price_raw=_text_or_none(price),
        availability_raw=_text_or_none(stock),
        category_raw=None,
    )
