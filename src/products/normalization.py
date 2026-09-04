from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, urlunsplit

from .models import Availability, Currency, ProductNormalizedData, ProductObservation


_PRICE_WITH_SYMBOL_RE = re.compile(
    r"^\s*(?P<sign>-)?\s*(?P<currency>[£$])\s*(?P<amount>\d+(?:\.\d+)?)\s*$"
)
_PLAIN_PRICE_RE = re.compile(r"^\s*(?P<sign>-)?\s*(?P<amount>\d+(?:\.\d+)?)\s*$")
_CURRENCY_BY_SYMBOL = {"£": Currency.GBP, "$": Currency.USD}
_BOOKS_IN_STOCK_RE = re.compile(
    r"^\s*In stock(?:\s*\((?P<quantity>\d+) available\))?\s*$",
    re.IGNORECASE,
)
_SCRAPEME_IN_STOCK_RE = re.compile(r"^\s*(?P<quantity>\d+)\s+in stock\s*$", re.IGNORECASE)
_OUT_OF_STOCK_RE = re.compile(r"^\s*Out of stock\s*$", re.IGNORECASE)


def canonicalize_product_url(url: str | None) -> str | None:
    if not url:
        return None

    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, "", ""))


def _normalize_price(
    raw: str | None,
    currency_raw: str | None,
) -> tuple[Decimal | None, Currency | None]:
    if raw is None:
        return None, None

    symbol_match = _PRICE_WITH_SYMBOL_RE.match(raw)
    if symbol_match:
        try:
            amount = Decimal(symbol_match.group("amount"))
        except InvalidOperation:
            return None, None
        if symbol_match.group("sign") == "-":
            amount = -amount
        return amount, _CURRENCY_BY_SYMBOL[symbol_match.group("currency")]

    plain_match = _PLAIN_PRICE_RE.match(raw)
    if not plain_match or currency_raw is None:
        return None, None

    try:
        currency = Currency(currency_raw.strip().upper())
        amount = Decimal(plain_match.group("amount"))
    except (ValueError, InvalidOperation):
        return None, None

    if plain_match.group("sign") == "-":
        amount = -amount
    return amount, currency


def _normalize_availability(
    source: str,
    raw: str | None,
) -> tuple[Availability | None, int | None]:
    if raw is None:
        return None, None

    if _OUT_OF_STOCK_RE.match(raw):
        return Availability.OUT_OF_STOCK, 0

    if source == "books_to_scrape":
        match = _BOOKS_IN_STOCK_RE.match(raw)
        if match:
            quantity_raw = match.group("quantity")
            quantity = int(quantity_raw) if quantity_raw is not None else None
            return Availability.IN_STOCK, quantity

    if source == "scrapeme_live":
        match = _SCRAPEME_IN_STOCK_RE.match(raw)
        if match:
            return Availability.IN_STOCK, int(match.group("quantity"))

    if source == "scrapify_js":
        normalized = raw.strip().lower()
        if normalized == "true":
            return Availability.IN_STOCK, None
        if normalized == "false":
            return Availability.OUT_OF_STOCK, None

    return None, None


def normalize_observation(observation: ProductObservation) -> ProductNormalizedData:
    price, currency = _normalize_price(observation.price_raw, observation.currency_raw)
    availability, quantity = _normalize_availability(
        observation.source,
        observation.availability_raw,
    )

    title = observation.title_raw.strip() if observation.title_raw is not None else None
    category = observation.category_raw.strip() if observation.category_raw is not None else None
    source_record_id = (
        observation.source_record_id_raw.strip()
        if observation.source_record_id_raw is not None
        else None
    )
    source_record_id = source_record_id or None

    if observation.canonical_product_url_raw is not None:
        canonical_product_url = canonicalize_product_url(
            observation.canonical_product_url_raw
        )
    elif source_record_id is None:
        canonical_product_url = canonicalize_product_url(observation.source_url)
    else:
        canonical_product_url = None

    return ProductNormalizedData(
        source=observation.source,
        source_url=observation.source_url,
        canonical_product_url=canonical_product_url,
        source_record_id=source_record_id,
        observed_at=observation.observed_at,
        title=title,
        price=price,
        currency=currency,
        availability=availability,
        quantity=quantity,
        category=category or None,
    )
