from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.acquisition.models import RawEvidence
from src.books.models import StateDecision
from src.books.service import process_book_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "book_product.html"
URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
T0 = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def fixture_evidence() -> RawEvidence:
    return RawEvidence.capture(
        evidence_id="evidence-pipeline-001",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=FIXTURE.read_text(encoding="utf-8"),
    )


def test_fixture_runs_from_exact_evidence_to_create_state_decision() -> None:
    result = process_book_evidence(
        fixture_evidence(),
        changed_at=T0,
    )

    assert result.observation.evidence_id == result.evidence.id
    assert result.observation.price_raw == "£51.77"
    assert result.normalized.price == Decimal("51.77")
    assert result.transition.decision == StateDecision.CREATE
    assert result.transition.current_state is not None
    assert result.transition.current_state.price == Decimal("51.77")
    assert result.transition.history_entry is not None


def test_reprocessing_same_fixture_reaches_no_change_decision() -> None:
    first = process_book_evidence(
        fixture_evidence(),
        changed_at=T0,
    )
    current = first.transition.current_state
    assert current is not None

    second = process_book_evidence(
        fixture_evidence(),
        current=current,
        changed_at=T0,
    )

    assert second.transition.decision == StateDecision.NO_CHANGE
    assert second.transition.current_state == current
    assert second.transition.history_entry is None
