from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy.orm import Session, sessionmaker

from src.acquisition.fetch import DEFAULT_TIMEOUT_SECONDS, fetch_url
from src.acquisition.models import RawEvidence
from src.books.models import (
    BookNormalizedData,
    BookObservation,
    StateTransitionResult,
)
from src.books.normalization import normalize_observation
from src.books.parser import parse_book
from src.books.state import process_normalized_book

from .repositories import (
    apply_state_transition,
    find_book_row,
    persist_book_observation,
    persist_raw_evidence,
    row_to_current_state,
)


@dataclass(frozen=True)
class PersistedBookRun:
    evidence: RawEvidence
    observation: BookObservation
    normalized: BookNormalizedData
    transition: StateTransitionResult
    observation_id: int
    book_id: int | None


def persist_book_evidence(
    session_factory: sessionmaker[Session],
    evidence: RawEvidence,
    *,
    changed_at: datetime | None = None,
) -> PersistedBookRun:
    """Persist one evidence-to-state run.

    Raw evidence is committed first so exact external input survives even if a later
    extraction or state-persistence step fails. Current-state update and history
    append are then committed in one transaction.
    """

    with session_factory() as session:
        with session.begin():
            persist_raw_evidence(session, evidence)

    observation = parse_book(evidence)
    normalized = normalize_observation(observation)

    with session_factory() as session:
        with session.begin():
            existing_book = find_book_row(
                session,
                source=normalized.source,
                canonical_product_url=normalized.canonical_product_url,
            )
            current = (
                row_to_current_state(existing_book)
                if existing_book is not None
                else None
            )

            transition = process_normalized_book(
                current,
                normalized,
                changed_at=changed_at,
            )

            observation_row = persist_book_observation(
                session,
                observation=observation,
                normalized=normalized,
                transition=transition,
            )

            book_row = apply_state_transition(
                session,
                existing_book=existing_book,
                transition=transition,
                observation_id=observation_row.id,
            )

            observation_id = observation_row.id
            book_id = book_row.id if book_row is not None else None

    return PersistedBookRun(
        evidence=evidence,
        observation=observation,
        normalized=normalized,
        transition=transition,
        observation_id=observation_id,
        book_id=book_id,
    )


def persist_book_url(
    session_factory: sessionmaker[Session],
    url: str,
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    evidence_id: str | None = None,
    fetched_at: datetime | None = None,
    changed_at: datetime | None = None,
) -> PersistedBookRun:
    evidence = fetch_url(
        url,
        client=client,
        timeout_seconds=timeout_seconds,
        evidence_id=evidence_id,
        fetched_at=fetched_at,
    )
    return persist_book_evidence(
        session_factory,
        evidence,
        changed_at=changed_at,
    )
