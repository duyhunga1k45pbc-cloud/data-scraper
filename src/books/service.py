from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx

from src.acquisition.fetch import DEFAULT_TIMEOUT_SECONDS, fetch_url
from src.acquisition.models import RawEvidence

from .models import BookNormalizedData, BookObservation, CurrentBookState, StateTransitionResult
from .normalization import normalize_observation
from .parser import parse_book
from .state import process_normalized_book


@dataclass(frozen=True)
class BookPipelineResult:
    """Trace of one book-processing run up to the state-decision boundary."""

    evidence: RawEvidence
    observation: BookObservation
    normalized: BookNormalizedData
    transition: StateTransitionResult


def process_book_evidence(
    evidence: RawEvidence,
    *,
    current: CurrentBookState | None = None,
    changed_at: datetime | None = None,
) -> BookPipelineResult:
    """Process captured evidence through extraction, normalization and state decision."""

    observation = parse_book(evidence)
    normalized = normalize_observation(observation)
    transition = process_normalized_book(
        current,
        normalized,
        changed_at=changed_at,
    )

    return BookPipelineResult(
        evidence=evidence,
        observation=observation,
        normalized=normalized,
        transition=transition,
    )


def process_book_url(
    url: str,
    *,
    current: CurrentBookState | None = None,
    client: httpx.Client | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    evidence_id: str | None = None,
    fetched_at: datetime | None = None,
    changed_at: datetime | None = None,
) -> BookPipelineResult:
    """Fetch one book URL and run it through the M0 pipeline to a state decision."""

    evidence = fetch_url(
        url,
        client=client,
        timeout_seconds=timeout_seconds,
        evidence_id=evidence_id,
        fetched_at=fetched_at,
    )
    return process_book_evidence(
        evidence,
        current=current,
        changed_at=changed_at,
    )
