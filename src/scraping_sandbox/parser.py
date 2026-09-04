from __future__ import annotations

import json
from decimal import Decimal

from bs4 import BeautifulSoup

from src.acquisition.models import RawEvidence
from src.products.models import ProductObservation, ProductVariantObservation


SOURCE = "scraping_sandbox"
EXTRACTOR_VERSION = "scraping-sandbox-json-v1"


class ScrapingSandboxExtractionError(ValueError):
    pass


def _raw_decimal(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (int, float, str)):
        return str(value)
    return None


def _raw_bool(value: object) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    return None


def _extract_product_json(evidence: RawEvidence) -> dict[str, object]:
    soup = BeautifulSoup(evidence.body, "lxml")
    for pre in soup.find_all("pre"):
        text = pre.get_text("", strip=True)
        if not text.startswith("{") or '"variants"' not in text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "id" in payload and "title" in payload:
            return payload
    raise ScrapingSandboxExtractionError("PRODUCT_JSON_NOT_FOUND")


def parse_product(evidence: RawEvidence) -> ProductObservation:
    payload = _extract_product_json(evidence)

    variants_payload = payload.get("variants")
    if not isinstance(variants_payload, list):
        raise ScrapingSandboxExtractionError("VARIANTS_NOT_LIST")

    variants: list[ProductVariantObservation] = []
    for item in variants_payload:
        if not isinstance(item, dict):
            raise ScrapingSandboxExtractionError("VARIANT_NOT_OBJECT")

        options: list[tuple[str, str]] = []
        for name in ("color", "size"):
            value = item.get(name)
            if isinstance(value, str) and value.strip():
                options.append((name, value))

        variants.append(
            ProductVariantObservation(
                sku_raw=item.get("sku") if isinstance(item.get("sku"), str) else None,
                price_raw=_raw_decimal(item.get("price")),
                availability_raw=_raw_bool(item.get("inStock")),
                options_raw=tuple(options),
            )
        )

    category = payload.get("category") if isinstance(payload.get("category"), str) else None
    source_record_id = payload.get("id")
    if isinstance(source_record_id, bool) or not isinstance(source_record_id, (int, str)):
        source_record_id_raw = None
    else:
        source_record_id_raw = str(source_record_id)

    return ProductObservation(
        evidence_id=evidence.id,
        extractor_version=EXTRACTOR_VERSION,
        source=SOURCE,
        source_url=evidence.source_url,
        observed_at=evidence.fetched_at,
        title_raw=payload.get("title") if isinstance(payload.get("title"), str) else None,
        price_raw=_raw_decimal(payload.get("price")),
        compare_at_price_raw=_raw_decimal(payload.get("compareAtPrice")),
        currency_raw="USD",
        availability_raw=_raw_bool(payload.get("inStock")),
        category_raw=category,
        categories_raw=(category,) if category else (),
        sku_raw=payload.get("sku") if isinstance(payload.get("sku"), str) else None,
        source_record_id_raw=source_record_id_raw,
        canonical_product_url_raw=evidence.source_url,
        variants_raw=tuple(variants),
    )
