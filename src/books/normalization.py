from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, urlunsplit

from .models import Availability, BookNormalizedData, BookObservation, Currency


_PRICE_RE = re.compile(r"^\s*(?P<sign>-)?\s*(?P<currency>£)\s*(?P<amount>\d+(?:\.\d+)?)\s*$")
_IN_STOCK_RE = re.compile(r"^\s*In stock(?:\s*\((?P<quantity>\d+) available\))?\s*$", re.IGNORECASE)
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


def _normalize_price(raw: str | None) -> tuple[Decimal | None, Currency | None]:
    if raw is None:
        return None, None

    match = _PRICE_RE.match(raw)
    if not match:
        return None, None

    try:
        amount = Decimal(match.group("amount"))
    except InvalidOperation:
        return None, None

    if match.group("sign") == "-":
        amount = -amount

    return amount, Currency.GBP


def _normalize_availability(raw: str | None) -> tuple[Availability | None, int | None]:
    if raw is None:
        return None, None

    in_stock = _IN_STOCK_RE.match(raw)
    if in_stock:
        quantity_raw = in_stock.group("quantity")
        quantity = int(quantity_raw) if quantity_raw is not None else None
        return Availability.IN_STOCK, quantity

    if _OUT_OF_STOCK_RE.match(raw):
        return Availability.OUT_OF_STOCK, 0

    return None, None


def normalize_observation(observation: BookObservation) -> BookNormalizedData:
    price, currency = _normalize_price(observation.price_raw)
    availability, quantity = _normalize_availability(observation.availability_raw)

    title = observation.title_raw.strip() if observation.title_raw is not None else None
    category = observation.category_raw.strip() if observation.category_raw is not None else None

    return BookNormalizedData(
        source=observation.source,
        canonical_product_url=canonicalize_product_url(observation.source_url),
        observed_at=observation.observed_at,
        title=title,
        price=price,
        currency=currency,
        availability=availability,
        quantity=quantity,
        category=category or None,
    )
