from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from src.acquisition.models import RawEvidence
from src.products.models import StateDecision
from src.products.service import process_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scraping_sandbox_product.html"
URL = "https://scrapingsandbox.com/product/1"
T0 = datetime(2026, 9, 5, 3, 0, tzinfo=timezone.utc)
_PRE_RE = re.compile(r"(<pre>)(.*?)(</pre>)", re.DOTALL)


def _base_payload() -> dict[str, object]:
    body = FIXTURE.read_text(encoding="utf-8")
    match = _PRE_RE.search(body)
    assert match is not None
    return json.loads(match.group(2))


def _evidence(
    evidence_id: str,
    *,
    payload: dict[str, object] | None = None,
    fetched_at: datetime = T0,
) -> RawEvidence:
    body = FIXTURE.read_text(encoding="utf-8")
    payload = deepcopy(payload if payload is not None else _base_payload())
    rendered = json.dumps(payload, indent=2)
    body = _PRE_RE.sub(rf"\1{rendered}\3", body, count=1)
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=URL,
        fetched_at=fetched_at,
        status_code=200,
        content_type="text/html",
        body=body,
    )


def _create_state():
    result = process_product_evidence(_evidence("m4-create"), changed_at=T0)
    assert result.transition.decision == StateDecision.CREATE
    assert result.transition.current_state is not None
    return result.transition.current_state


def test_m4_product_price_change_creates_one_update_with_previous_and_new_state() -> None:
    current = _create_state()
    payload = _base_payload()
    payload["price"] = 149.99

    changed_at = T0 + timedelta(minutes=1)
    result = process_product_evidence(
        _evidence("m4-product-price", payload=payload, fetched_at=changed_at),
        current=current,
        changed_at=changed_at,
    )

    assert result.transition.decision == StateDecision.UPDATE
    history = result.transition.history_entry
    assert history is not None
    assert history.previous_state is not None
    assert history.previous_state.price == Decimal("155.62")
    assert history.new_state.price == Decimal("149.99")


def test_m4_compare_at_price_removal_is_a_real_state_change() -> None:
    current = _create_state()
    payload = _base_payload()
    payload["compareAtPrice"] = None

    result = process_product_evidence(
        _evidence("m4-compare-price", payload=payload),
        current=current,
        changed_at=T0,
    )

    assert result.transition.decision == StateDecision.UPDATE
    assert result.transition.current_state is not None
    assert result.transition.current_state.compare_at_price is None


def test_m4_variant_stock_change_creates_one_product_update() -> None:
    current = _create_state()
    payload = _base_payload()
    variants = payload["variants"]
    assert isinstance(variants, list)
    assert isinstance(variants[0], dict)
    variants[0]["inStock"] = False

    result = process_product_evidence(
        _evidence("m4-stock", payload=payload),
        current=current,
        changed_at=T0,
    )

    assert result.transition.decision == StateDecision.UPDATE
    assert result.transition.current_state is not None
    changed_variant = next(
        variant
        for variant in result.transition.current_state.variants
        if variant.key == "sku:SKU-HEA-0001-PIN-XXL"
    )
    assert changed_variant.availability.value == "OUT_OF_STOCK"
    assert result.transition.history_entry is not None


def test_m4_variant_addition_and_removal_are_real_state_changes() -> None:
    current = _create_state()
    payload = _base_payload()
    variants = payload["variants"]
    assert isinstance(variants, list)
    variants.append(
        {
            "color": "Black",
            "size": "M",
            "sku": "SKU-HEA-0001-BLA-M",
            "inStock": True,
            "price": 154.10,
        }
    )

    added = process_product_evidence(
        _evidence("m4-variant-added", payload=payload),
        current=current,
        changed_at=T0,
    )
    assert added.transition.decision == StateDecision.UPDATE
    assert added.transition.current_state is not None
    assert len(added.transition.current_state.variants) == 5

    payload_removed = deepcopy(payload)
    variants_removed = payload_removed["variants"]
    assert isinstance(variants_removed, list)
    variants_removed.pop(1)

    removed = process_product_evidence(
        _evidence("m4-variant-removed", payload=payload_removed),
        current=added.transition.current_state,
        changed_at=T0,
    )
    assert removed.transition.decision == StateDecision.UPDATE
    assert removed.transition.current_state is not None
    assert len(removed.transition.current_state.variants) == 4


def test_m4_reordering_collections_does_not_create_fake_business_change() -> None:
    current = _create_state()
    payload = _base_payload()
    payload["category"] = "Health"
    variants = payload["variants"]
    assert isinstance(variants, list)
    variants.reverse()
    for item in variants:
        assert isinstance(item, dict)
        # JSON object key order and the parser's option extraction order are not
        # product semantics; the variant identity and option names/values are.
        if "color" in item and "size" in item:
            item["color"], item["size"] = item["color"], item["size"]

    result = process_product_evidence(
        _evidence("m4-reordered", payload=payload),
        current=current,
        changed_at=T0,
    )

    assert result.transition.decision == StateDecision.NO_CHANGE
    assert result.transition.history_entry is None


def test_m4_category_presentation_order_does_not_create_fake_change() -> None:
    scrapeme_fixture = Path(__file__).parents[1] / "fixtures" / "scrapeme_product.html"
    scrapeme_url = "https://scrapeme.live/shop/Charizard/"
    original_body = scrapeme_fixture.read_text(encoding="utf-8")
    reordered_body = original_body.replace(
        "<a>Flame</a>, <a>Pokemon</a>",
        "<a>Pokemon</a>, <a>Flame</a>",
    )
    assert reordered_body != original_body

    first = process_product_evidence(
        RawEvidence.capture(
            evidence_id="m4-categories-before",
            source_url=scrapeme_url,
            fetched_at=T0,
            status_code=200,
            content_type="text/html",
            body=original_body,
        ),
        changed_at=T0,
    )
    assert first.transition.current_state is not None

    second = process_product_evidence(
        RawEvidence.capture(
            evidence_id="m4-categories-after",
            source_url=scrapeme_url,
            fetched_at=T0 + timedelta(minutes=1),
            status_code=200,
            content_type="text/html",
            body=reordered_body,
        ),
        current=first.transition.current_state,
        changed_at=T0 + timedelta(minutes=1),
    )

    assert second.transition.decision == StateDecision.NO_CHANGE
    assert second.transition.history_entry is None
