from datetime import datetime, timezone
from hashlib import sha256

import httpx

from src.acquisition.fetch import fetch_url


URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
T0 = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def test_fetch_url_captures_http_response_as_raw_evidence() -> None:
    body = "<html><body><h1>A Light in the Attic</h1></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == URL
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=body,
            request=request,
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        evidence = fetch_url(
            URL,
            client=client,
            evidence_id="evidence-fetch-001",
            fetched_at=T0,
        )

    assert evidence.id == "evidence-fetch-001"
    assert evidence.source_url == URL
    assert evidence.fetched_at == T0
    assert evidence.status_code == 200
    assert evidence.content_type == "text/html; charset=utf-8"
    assert evidence.body == body
    assert evidence.body_hash == sha256(body.encode("utf-8")).hexdigest()


def test_fetch_url_preserves_non_success_response_as_evidence() -> None:
    body = "<html><body>Service unavailable</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            headers={"content-type": "text/html"},
            text=body,
            request=request,
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        evidence = fetch_url(
            URL,
            client=client,
            evidence_id="evidence-fetch-503",
            fetched_at=T0,
        )

    assert evidence.status_code == 503
    assert evidence.body == body
    assert evidence.body_hash == sha256(body.encode("utf-8")).hexdigest()
