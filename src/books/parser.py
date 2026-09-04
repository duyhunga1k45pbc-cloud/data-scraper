from __future__ import annotations

from bs4 import BeautifulSoup

from src.acquisition.models import RawEvidence

from .models import BookObservation


EXTRACTOR_VERSION = "books-to-scrape-v1"
SOURCE = "books_to_scrape"


class BookExtractionError(ValueError):
    pass


def _text_or_none(node) -> str | None:
    if node is None:
        return None
    text = node.get_text(" ", strip=True)
    return text or None


def _extract_category(soup: BeautifulSoup) -> str | None:
    breadcrumb = soup.select_one("ul.breadcrumb")
    if breadcrumb is None:
        return None

    links = breadcrumb.select("li a")
    if not links:
        return None

    # On Books to Scrape the final breadcrumb link is the book category;
    # the active final <li> is the book title and has no link.
    return _text_or_none(links[-1])


def parse_book(evidence: RawEvidence) -> BookObservation:
    soup = BeautifulSoup(evidence.body, "lxml")
    product = soup.select_one("div.product_main")
    if product is None:
        raise BookExtractionError("PRODUCT_MAIN_NOT_FOUND")

    return BookObservation(
        evidence_id=evidence.id,
        extractor_version=EXTRACTOR_VERSION,
        source=SOURCE,
        source_url=evidence.source_url,
        observed_at=evidence.fetched_at,
        title_raw=_text_or_none(product.select_one("h1")),
        price_raw=_text_or_none(product.select_one("p.price_color")),
        availability_raw=_text_or_none(product.select_one("p.instock.availability")),
        category_raw=_extract_category(soup),
    )
