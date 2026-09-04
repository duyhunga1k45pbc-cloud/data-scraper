from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import httpx
from sqlalchemy.orm import Session, sessionmaker

from src.acquisition.fetch import DEFAULT_TIMEOUT_SECONDS, fetch_url
from src.acquisition.models import RawEvidence
from src.products.models import (
    ProductNormalizedData,
    ProductObservation,
    StateTransitionResult,
)
from src.products.normalization import normalize_observation
from src.products.service import parse_product_evidence
from src.products.state import process_normalized_product

from .repositories import (
    apply_state_transition,
    find_product_row,
    persist_product_observation,
    persist_raw_evidence,
    row_to_current_state,
)


@dataclass(frozen=True)
class PersistedProductRun:
    evidence: RawEvidence
    observation: ProductObservation
    normalized: ProductNormalizedData
    transition: StateTransitionResult
    observation_id: int
    product_id: int | None

    @property
    def book_id(self) -> int | None:
        """M0 compatibility alias."""
        return self.product_id


def _persist_observations_transaction(
    session_factory: sessionmaker[Session],
    evidence: RawEvidence,
    observations: Iterable[ProductObservation],
    *,
    changed_at: datetime | None,
) -> tuple[PersistedProductRun, ...]:
    results: list[PersistedProductRun] = []

    with session_factory() as session:
        with session.begin():
            for observation in observations:
                normalized = normalize_observation(observation)
                existing_product = find_product_row(
                    session,
                    source=normalized.source,
                    canonical_product_url=normalized.canonical_product_url,
                    source_record_id=normalized.source_record_id,
                )
                current = (
                    row_to_current_state(existing_product)
                    if existing_product is not None
                    else None
                )

                transition = process_normalized_product(
                    current,
                    normalized,
                    changed_at=changed_at,
                )

                observation_row = persist_product_observation(
                    session,
                    observation=observation,
                    normalized=normalized,
                    transition=transition,
                )

                product_row = apply_state_transition(
                    session,
                    existing_product=existing_product,
                    transition=transition,
                    observation_id=observation_row.id,
                )

                results.append(
                    PersistedProductRun(
                        evidence=evidence,
                        observation=observation,
                        normalized=normalized,
                        transition=transition,
                        observation_id=observation_row.id,
                        product_id=product_row.id if product_row is not None else None,
                    )
                )

    return tuple(results)


def persist_product_observations(
    session_factory: sessionmaker[Session],
    evidence: RawEvidence,
    observations: Iterable[ProductObservation],
    *,
    changed_at: datetime | None = None,
) -> tuple[PersistedProductRun, ...]:
    """Persist one evidence payload that may contain one or many product records.

    Raw evidence commits first so exact source input survives a later parser or
    state transaction failure. All observations derived from that evidence are
    then processed in one state transaction.
    """

    with session_factory() as session:
        with session.begin():
            persist_raw_evidence(session, evidence)

    return _persist_observations_transaction(
        session_factory,
        evidence,
        observations,
        changed_at=changed_at,
    )


def persist_product_evidence(
    session_factory: sessionmaker[Session],
    evidence: RawEvidence,
    *,
    changed_at: datetime | None = None,
) -> PersistedProductRun:
    """Persist one single-product evidence-to-state run."""

    with session_factory() as session:
        with session.begin():
            persist_raw_evidence(session, evidence)

    observation = parse_product_evidence(evidence)
    results = _persist_observations_transaction(
        session_factory,
        evidence,
        (observation,),
        changed_at=changed_at,
    )
    return results[0]


def persist_product_url(
    session_factory: sessionmaker[Session],
    url: str,
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    evidence_id: str | None = None,
    fetched_at: datetime | None = None,
    changed_at: datetime | None = None,
) -> PersistedProductRun:
    evidence = fetch_url(
        url,
        client=client,
        timeout_seconds=timeout_seconds,
        evidence_id=evidence_id,
        fetched_at=fetched_at,
    )
    return persist_product_evidence(
        session_factory,
        evidence,
        changed_at=changed_at,
    )


PersistedBookRun = PersistedProductRun


def persist_book_evidence(
    session_factory: sessionmaker[Session],
    evidence: RawEvidence,
    *,
    changed_at: datetime | None = None,
) -> PersistedProductRun:
    return persist_product_evidence(
        session_factory,
        evidence,
        changed_at=changed_at,
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
) -> PersistedProductRun:
    return persist_product_url(
        session_factory,
        url,
        client=client,
        timeout_seconds=timeout_seconds,
        evidence_id=evidence_id,
        fetched_at=fetched_at,
        changed_at=changed_at,
    )
