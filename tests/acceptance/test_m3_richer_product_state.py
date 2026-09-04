from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.acquisition.models import RawEvidence
from src.products.models import StateDecision
from src.products.service import process_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scraping_sandbox_product.html"
URL = "https://scrapingsandbox.com/product/1"
T0 = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)


def _evidence(evidence_id: str, *, variant_price: str = "153.43") -> RawEvidence:
    body = FIXTURE.read_text(encoding="utf-8").replace('"price": 153.43', f'"price": {variant_price}', 1)
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html",
        body=body,
    )


def test_m3_richer_product_reaches_current_state_without_losing_semantics() -> None:
    result = process_product_evidence(_evidence("m3-create"), changed_at=T0)

    assert result.transition.decision == StateDecision.CREATE
    state = result.transition.current_state
    assert state is not None
    assert state.price == Decimal("155.62")
    assert state.compare_at_price == Decimal("206.69")
    assert state.sku == "SKU-HEA-0001"
    assert state.categories == ("Health",)
    assert len(state.variants) == 4
    assert state.variants[2].availability.value == "OUT_OF_STOCK"


def test_m3_variant_price_change_is_a_real_product_state_transition() -> None:
    first = process_product_evidence(_evidence("m3-before"), changed_at=T0)
    assert first.transition.current_state is not None

    second = process_product_evidence(
        _evidence("m3-after", variant_price="149.99"),
        current=first.transition.current_state,
        changed_at=T0,
    )

    assert second.transition.decision == StateDecision.UPDATE
    assert second.transition.current_state is not None
    assert second.transition.current_state.variants[0].price == Decimal("149.99")
    assert second.transition.history_entry is not None
