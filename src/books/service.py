"""Books-to-Scrape compatibility wrapper around the M1 product pipeline."""

from __future__ import annotations

from datetime import datetime

import httpx

from src.acquisition.fetch import DEFAULT_TIMEOUT_SECONDS
from src.acquisition.models import RawEvidence
from src.products.models import CurrentProductState
from src.products.service import (
    ProductPipelineResult,
    process_product_evidence,
    process_product_url,
)

BookPipelineResult = ProductPipelineResult


def process_book_evidence(
    evidence: RawEvidence,
    *,
    current: CurrentProductState | None = None,
    changed_at: datetime | None = None,
) -> ProductPipelineResult:
    return process_product_evidence(
        evidence,
        current=current,
        changed_at=changed_at,
    )


def process_book_url(
    url: str,
    *,
    current: CurrentProductState | None = None,
    client: httpx.Client | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    evidence_id: str | None = None,
    fetched_at: datetime | None = None,
    changed_at: datetime | None = None,
) -> ProductPipelineResult:
    return process_product_url(
        url,
        current=current,
        client=client,
        timeout_seconds=timeout_seconds,
        evidence_id=evidence_id,
        fetched_at=fetched_at,
        changed_at=changed_at,
    )
