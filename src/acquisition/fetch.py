from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import httpx

from .models import RawEvidence


DEFAULT_TIMEOUT_SECONDS = 10.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _capture_response(
    response: httpx.Response,
    *,
    evidence_id: str,
    fetched_at: datetime,
) -> RawEvidence:
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=str(response.url),
        fetched_at=fetched_at,
        status_code=response.status_code,
        content_type=response.headers.get("content-type", ""),
        body=response.text,
    )


def fetch_url(
    url: str,
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    evidence_id: str | None = None,
    fetched_at: datetime | None = None,
) -> RawEvidence:
    """Fetch one URL and capture the HTTP response as RawEvidence.

    HTTP error status codes are still evidence and are therefore captured
    instead of being converted into exceptions. Transport-level failures
    (DNS, connection, timeout, etc.) are allowed to propagate from httpx;
    M0 does not yet define a persisted acquisition-failure model.
    """

    evidence_id = evidence_id or str(uuid4())
    fetched_at = fetched_at or _utc_now()

    if client is not None:
        response = client.get(url)
        return _capture_response(
            response,
            evidence_id=evidence_id,
            fetched_at=fetched_at,
        )

    with httpx.Client(
        follow_redirects=True,
        timeout=timeout_seconds,
    ) as owned_client:
        response = owned_client.get(url)
        return _capture_response(
            response,
            evidence_id=evidence_id,
            fetched_at=fetched_at,
        )
