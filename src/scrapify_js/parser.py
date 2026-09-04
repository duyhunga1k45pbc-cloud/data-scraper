from __future__ import annotations

import json
from decimal import Decimal

from src.acquisition.models import RawEvidence
from src.products.models import ProductObservation


SOURCE = "scrapify_js"
EXTRACTOR_VERSION = "scrapify-js-json-v1"


class ScrapifyCatalogExtractionError(ValueError):
    pass


def _raw_decimal(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, int):
        return str(value)
    return str(value)


def parse_catalog(evidence: RawEvidence) -> tuple[ProductObservation, ...]:
    try:
        payload = json.loads(evidence.body, parse_float=Decimal)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ScrapifyCatalogExtractionError("INVALID_JSON") from exc

    products = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(products, list):
        raise ScrapifyCatalogExtractionError("PRODUCTS_ARRAY_NOT_FOUND")

    observations: list[ProductObservation] = []
    for index, item in enumerate(products):
        if not isinstance(item, dict):
            raise ScrapifyCatalogExtractionError(f"INVALID_PRODUCT_RECORD:{index}")

        record_id = item.get("id")
        in_stock = item.get("in_stock")
        availability_raw = (
            "true" if in_stock is True else "false" if in_stock is False else None
        )

        observations.append(
            ProductObservation(
                evidence_id=evidence.id,
                extractor_version=EXTRACTOR_VERSION,
                source=SOURCE,
                source_url=evidence.source_url,
                observed_at=evidence.fetched_at,
                title_raw=item.get("title") if isinstance(item.get("title"), str) else None,
                price_raw=_raw_decimal(item.get("price")),
                availability_raw=availability_raw,
                category_raw=(
                    item.get("category") if isinstance(item.get("category"), str) else None
                ),
                currency_raw=(
                    item.get("currency") if isinstance(item.get("currency"), str) else None
                ),
                source_record_id_raw=(
                    record_id if isinstance(record_id, str) else None
                ),
                canonical_product_url_raw=None,
            )
        )

    return tuple(observations)
