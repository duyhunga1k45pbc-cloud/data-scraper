from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx

from src.acquisition.fetch import DEFAULT_TIMEOUT_SECONDS, fetch_url
from src.acquisition.models import RawEvidence
from src.books.parser import parse_book
from src.scrapeme.parser import parse_product as parse_scrapeme_product
from src.scraping_sandbox.parser import parse_product as parse_scraping_sandbox_product

from .models import (
    CurrentProductState,
    ProductNormalizedData,
    ProductObservation,
    StateTransitionResult,
)
from .normalization import normalize_observation
from .source import source_for_url
from .state import process_normalized_product


@dataclass(frozen=True)
class ProductPipelineResult:
    evidence: RawEvidence
    observation: ProductObservation
    normalized: ProductNormalizedData
    transition: StateTransitionResult


def parse_product_evidence(evidence: RawEvidence) -> ProductObservation:
    source = source_for_url(evidence.source_url)
    if source == "books_to_scrape":
        return parse_book(evidence)
    if source == "scrapeme_live":
        return parse_scrapeme_product(evidence)
    if source == "scraping_sandbox":
        return parse_scraping_sandbox_product(evidence)
    raise AssertionError(f"unhandled source: {source}")


def process_product_evidence(
    evidence: RawEvidence,
    *,
    current: CurrentProductState | None = None,
    changed_at: datetime | None = None,
) -> ProductPipelineResult:
    observation = parse_product_evidence(evidence)
    normalized = normalize_observation(observation)
    transition = process_normalized_product(
        current,
        normalized,
        changed_at=changed_at,
    )

    return ProductPipelineResult(
        evidence=evidence,
        observation=observation,
        normalized=normalized,
        transition=transition,
    )


def process_product_url(
    url: str,
    *,
    current: CurrentProductState | None = None,
    client: httpx.Client | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    evidence_id: str | None = None,
    fetched_at: datetime | None = None,
    changed_at: datetime | None = None,
) -> ProductPipelineResult:
    # Reject unsupported hosts before making a network request.
    source_for_url(url)
    evidence = fetch_url(
        url,
        client=client,
        timeout_seconds=timeout_seconds,
        evidence_id=evidence_id,
        fetched_at=fetched_at,
    )
    return process_product_evidence(
        evidence,
        current=current,
        changed_at=changed_at,
    )
