from __future__ import annotations

import inspect
import re
from dataclasses import MISSING, fields, is_dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from src.acquisition.models import RawEvidence
from src.products.models import ProductObservation

SOURCE = "web_scraping_dev"
HOST = "web-scraping.dev"
EXTRACTOR_VERSION = "web-scraping-dev-html-v1"
_PRODUCT_PATH = re.compile(r"^/product/(\d+)/?$")


class WebScrapingDevParseError(ValueError):
    pass


def _canonical_product_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname != HOST:
        raise WebScrapingDevParseError("WEB_SCRAPING_DEV_INVALID_PRODUCT_HOST")
    match = _PRODUCT_PATH.fullmatch(parsed.path)
    if match is None:
        raise WebScrapingDevParseError("WEB_SCRAPING_DEV_INVALID_PRODUCT_PATH")
    canonical = urlunsplit(("https", HOST, parsed.path.rstrip("/"), "", ""))
    return canonical, match.group(1)


def _text(node: Any) -> str | None:
    if node is None:
        return None
    value = node.get_text(" ", strip=True)
    return value or None


def _price_text(soup: BeautifulSoup) -> str | None:
    for node in soup.select(".product-price"):
        classes = set(node.get("class") or ())
        if "product-price-full" not in classes:
            value = _text(node)
            if value:
                return value
    return None


def _availability_text(soup: BeautifulSoup) -> str | None:
    explicit: list[bool] = []
    for node in soup.select(".stock-status[data-available]"):
        raw = str(node.get("data-available") or "").strip().lower()
        if raw in {"true", "1", "yes", "available", "in-stock", "in_stock"}:
            explicit.append(True)
        elif raw in {"false", "0", "no", "unavailable", "out-of-stock", "out_of_stock"}:
            explicit.append(False)
    if explicit:
        return "In stock" if any(explicit) else "Out of stock"

    # Fall back only to explicit source text; do not infer inventory from buttons,
    # purchase quantity selectors, or other presentation details.
    for node in soup.find_all(string=re.compile(r"\b(?:in stock|out of stock)\b", re.I)):
        value = str(node).strip().lower()
        if "out of stock" in value:
            return "Out of stock"
        if "in stock" in value:
            return "In stock"
    return None


def _observation_values(evidence: RawEvidence) -> dict[str, Any]:
    canonical_url, record_id = _canonical_product_url(evidence.source_url)
    soup = BeautifulSoup(evidence.body, "lxml")

    title = _text(soup.select_one("h3.product-title"))
    price = _price_text(soup)
    compare_at = _text(soup.select_one(".product-price-full"))
    availability = _availability_text(soup)

    if not title:
        raise WebScrapingDevParseError("WEB_SCRAPING_DEV_MISSING_TITLE")
    if not price:
        raise WebScrapingDevParseError("WEB_SCRAPING_DEV_MISSING_PRICE")
    if not availability:
        raise WebScrapingDevParseError("WEB_SCRAPING_DEV_MISSING_EXPLICIT_AVAILABILITY")

    # M19 intentionally preserves only fields that the base product page exposes
    # completely enough for the existing domain contract. The purchase-quantity
    # selector is not inventory. Variant rows are not emitted unless complete
    # variant price/availability tuples are available, so no values are invented.
    return {
        "evidence_id": evidence.id,
        "extractor_version": EXTRACTOR_VERSION,
        "source": SOURCE,
        "source_url": canonical_url,
        "observed_at": evidence.fetched_at,
        "source_record_id_raw": record_id,
        "source_record_id": record_id,
        "canonical_product_url_raw": canonical_url,
        "canonical_product_url": canonical_url,
        "title_raw": title,
        "price_raw": price,
        "compare_at_price_raw": compare_at,
        "availability_raw": availability,
        "quantity_raw": None,
        "category_raw": None,
        "sku_raw": None,
        "categories_raw": (),
        "variants_raw": (),
    }


def _construct_observation(values: dict[str, Any]) -> ProductObservation:
    """Adapt to the existing ProductObservation constructor without weakening it.

    M19 is a source extension, not a domain-model migration. We therefore pass
    only fields already present in the repository's current ProductObservation.
    If a future baseline adds an unknown required field, fail closed instead of
    silently manufacturing a value.
    """

    if is_dataclass(ProductObservation):
        kwargs: dict[str, Any] = {}
        for field in fields(ProductObservation):
            if field.name in values:
                kwargs[field.name] = values[field.name]
                continue
            has_default = field.default is not MISSING or field.default_factory is not MISSING
            if not has_default:
                raise RuntimeError(
                    "M19 unsupported required ProductObservation field: " + field.name
                )
        return ProductObservation(**kwargs)

    signature = inspect.signature(ProductObservation)
    kwargs = {}
    for name, parameter in signature.parameters.items():
        if name == "self" or parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue
        if name in values:
            kwargs[name] = values[name]
            continue
        if parameter.default is inspect.Parameter.empty:
            raise RuntimeError("M19 unsupported required ProductObservation field: " + name)
    return ProductObservation(**kwargs)


def parse_product_evidence(evidence: RawEvidence) -> tuple[ProductObservation, ...]:
    return (_construct_observation(_observation_values(evidence)),)
