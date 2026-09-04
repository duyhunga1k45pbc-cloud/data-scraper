from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.acquisition.models import RawEvidence
from src.products.models import StateDecision
from src.products.service import process_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scrapeme_product.html"
URL = "https://scrapeme.live/shop/Charizard/"
T0 = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)


def evidence(evidence_id: str = "scrapeme-m1-001") -> RawEvidence:
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html; charset=UTF-8",
        body=FIXTURE.read_text(),
    )


def test_m1_second_source_reaches_shared_product_state_contract() -> None:
    result = process_product_evidence(evidence(), changed_at=T0)

    assert result.transition.decision == StateDecision.CREATE
    assert result.transition.current_state is not None
    assert result.transition.current_state.identity.source == "scrapeme_live"
    assert result.transition.current_state.title == "Charizard"
    assert result.transition.current_state.price == Decimal("156.00")
    assert result.transition.current_state.quantity == 31


def test_m1_same_second_source_state_is_idempotent() -> None:
    first = process_product_evidence(evidence("scrapeme-m1-a"), changed_at=T0)
    assert first.transition.current_state is not None

    second = process_product_evidence(
        evidence("scrapeme-m1-b"),
        current=first.transition.current_state,
        changed_at=T0,
    )

    assert second.transition.decision == StateDecision.NO_CHANGE
    assert second.transition.history_entry is None
