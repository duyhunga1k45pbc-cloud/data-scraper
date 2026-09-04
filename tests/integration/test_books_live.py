import os

import pytest

from src.books.models import StateDecision
from src.books.service import process_book_url


URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE") != "1",
        reason="set RUN_LIVE=1 to run against Books to Scrape",
    ),
]


def test_live_books_to_scrape_reaches_state_decision_boundary() -> None:
    result = process_book_url(URL)

    assert result.evidence.status_code == 200
    assert "text/html" in result.evidence.content_type.lower()
    assert result.evidence.body
    assert result.observation.evidence_id == result.evidence.id
    assert result.normalized.price is not None
    assert result.normalized.price >= 0
    assert result.transition.decision == StateDecision.CREATE
    assert result.transition.current_state is not None
    assert result.transition.current_state.title == "A Light in the Attic"
