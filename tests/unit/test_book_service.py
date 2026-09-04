from datetime import datetime, timezone
from decimal import Decimal

import httpx

from src.books.models import StateDecision
from src.books.service import process_book_url


URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
T0 = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
HTML = """
<html>
<body>
  <ul class="breadcrumb">
    <li><a href="/catalogue/category/books_1/index.html">Books</a></li>
    <li><a href="/catalogue/category/books/poetry_23/index.html">Poetry</a></li>
  </ul>
  <div class="product_main">
    <h1>A Light in the Attic</h1>
    <p class="price_color">£51.77</p>
    <p class="instock availability">In stock (22 available)</p>
  </div>
</body>
</html>
"""


def test_process_book_url_composes_fetch_to_state_decision() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=HTML,
            request=request,
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        result = process_book_url(
            URL,
            client=client,
            evidence_id="evidence-service-001",
            fetched_at=T0,
            changed_at=T0,
        )

    assert result.evidence.id == "evidence-service-001"
    assert result.observation.evidence_id == result.evidence.id
    assert result.normalized.price == Decimal("51.77")
    assert result.transition.decision == StateDecision.CREATE
    assert result.transition.current_state is not None
    assert result.transition.current_state.price == Decimal("51.77")
