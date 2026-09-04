from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import httpx
from sqlalchemy.orm import Session, sessionmaker

from src.acquisition.fetch import DEFAULT_TIMEOUT_SECONDS, fetch_url
from src.acquisition.models import RawEvidence
from src.catalogs.models import (
    CatalogAcquisition,
    CatalogChunkResult,
    CatalogChunkStatus,
    CatalogRunStatus,
)
from src.products.models import (
    ProductNormalizedData,
    ProductObservation,
    StateTransitionResult,
)
from src.products.normalization import normalize_observation
from src.products.service import parse_product_evidence
from src.products.state import process_normalized_product, transition_product_absence

from .repositories import (
    apply_state_transition,
    find_product_row,
    list_product_rows_by_source,
    lock_catalog_scope_for_reconciliation,
    lock_product_identity_keys_for_transition,
    lock_product_identities_for_transition,
    persist_catalog_run,
    persist_catalog_run_chunk,
    persist_product_observation,
    persist_raw_evidence,
    row_to_current_state,
)


def _normalized_identity_key(data: ProductNormalizedData) -> str | None:
    if data.source_record_id:
        return f"id:{data.source_record_id}"
    if data.canonical_product_url:
        return f"url:{data.canonical_product_url}"
    return None

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

@dataclass(frozen=True)
class CatalogPersistenceResult:
    catalog_run_id: int
    coverage_status: CatalogRunStatus
    observed_results: tuple[PersistedProductRun, ...]
    absence_transitions: tuple[StateTransitionResult, ...]

    # M8-M13 callers historically treated catalog persistence as the tuple of
    # directly observed product results. Preserve read-only tuple-like access
    # while exposing absence transitions explicitly for M14 accounting.
    def __iter__(self):
        return iter(self.observed_results)

    def __len__(self) -> int:
        return len(self.observed_results)

    def __getitem__(self, index):
        return self.observed_results[index]




def _persist_observations_transaction(
    session_factory: sessionmaker[Session],
    evidence: RawEvidence,
    observations: Iterable[ProductObservation],
    *,
    changed_at: datetime | None,
) -> tuple[PersistedProductRun, ...]:
    results: list[PersistedProductRun] = []
    prepared = tuple(
        (observation, normalize_observation(observation))
        for observation in observations
    )

    with session_factory() as session:
        with session.begin():
            # M7: serialize by identity *before* reading current state. Unlike
            # SELECT FOR UPDATE, this also works when the product row does not
            # exist yet. All identity locks are acquired in stable order.
            lock_product_identities_for_transition(
                session,
                (normalized for _, normalized in prepared),
            )

            for observation, normalized in prepared:
                existing_product = find_product_row(
                    session,
                    source=normalized.source,
                    canonical_product_url=normalized.canonical_product_url,
                    source_record_id=normalized.source_record_id,
                    for_update=True,
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


def _persist_catalog_acquisition_transaction(
    session_factory: sessionmaker[Session],
    acquisition: CatalogAcquisition,
    *,
    changed_at: datetime | None,
) -> CatalogPersistenceResult:
    """Persist an evidence-backed catalog acquisition and reconcile presence.

    M9 removes the caller-supplied COMPLETE assertion from the primary path.
    Coverage is derived by ``CatalogAcquisition.coverage_status`` from the
    persisted chunk chain. Directly observed products are processed even when
    coverage is incomplete; absence can mutate trusted presence only when the
    proof is COMPLETE.
    """

    observations = acquisition.observations
    prepared = tuple(
        (observation, normalize_observation(observation))
        for observation in observations
    )
    evidence_by_id = {item.id: item for item in acquisition.evidence}
    complete = acquisition.coverage_status == CatalogRunStatus.COMPLETE

    results: list[PersistedProductRun] = []

    absence_transitions: list[StateTransitionResult] = []
    with session_factory() as session:
        with session.begin():
            lock_catalog_scope_for_reconciliation(
                session,
                source=acquisition.source,
                scope_key=acquisition.scope_key,
            )

            root_evidence_id = (
                acquisition.evidence[0].id if acquisition.evidence else None
            )
            catalog_run = persist_catalog_run(
                session,
                run_key=acquisition.run_key,
                evidence_id=root_evidence_id,
                source=acquisition.source,
                scope_key=acquisition.scope_key,
                start_ref=acquisition.start_ref,
                observed_at=acquisition.observed_at,
                status=acquisition.coverage_status.value,
                record_count=len(prepared),
            )
            for chunk in acquisition.chunks:
                persist_catalog_run_chunk(
                    session,
                    catalog_run_id=catalog_run.id,
                    sequence=chunk.sequence,
                    requested_ref=chunk.requested_ref,
                    attempted_at=chunk.attempted_at,
                    evidence_id=(chunk.evidence.id if chunk.evidence is not None else None),
                    status=chunk.status.value,
                    next_ref=chunk.next_ref,
                    record_count=chunk.record_count,
                    error_code=chunk.error_code,
                )

            lock_pairs: set[tuple[str, str]] = set()
            for _, normalized in prepared:
                key = _normalized_identity_key(normalized)
                if key is not None:
                    lock_pairs.add((normalized.source, key))

            if complete:
                lock_pairs.update(
                    (row.source, row.identity_key)
                    for row in list_product_rows_by_source(
                        session,
                        source=acquisition.source,
                    )
                )
            lock_product_identity_keys_for_transition(session, lock_pairs)

            seen_identity_keys: set[str] = set()
            for observation, normalized in prepared:
                key = _normalized_identity_key(normalized)
                if normalized.source == acquisition.source and key is not None:
                    seen_identity_keys.add(key)

                existing_product = find_product_row(
                    session,
                    source=normalized.source,
                    canonical_product_url=normalized.canonical_product_url,
                    source_record_id=normalized.source_record_id,
                    for_update=True,
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
                evidence = evidence_by_id.get(observation.evidence_id)
                if evidence is None:
                    raise RuntimeError(
                        f"observation {observation.evidence_id!r} has no catalog evidence"
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

            if complete:
                for row in list_product_rows_by_source(
                    session,
                    source=acquisition.source,
                ):
                    if row.identity_key in seen_identity_keys:
                        continue
                    locked = find_product_row(
                        session,
                        source=row.source,
                        identity_key=row.identity_key,
                        for_update=True,
                    )
                    if locked is None:
                        continue
                    transition = transition_product_absence(
                        row_to_current_state(locked),
                        observed_at=acquisition.observed_at,
                        changed_at=changed_at,
                    )
                    apply_state_transition(
                        session,
                        existing_product=locked,
                        transition=transition,
                        observation_id=None,
                        catalog_run_id=catalog_run.id,
                    )

                    absence_transitions.append(transition)

    return CatalogPersistenceResult(
        catalog_run_id=catalog_run.id,
        coverage_status=acquisition.coverage_status,
        observed_results=tuple(results),
        absence_transitions=tuple(absence_transitions),
    )


def persist_catalog_acquisition_result(
    session_factory: sessionmaker[Session],
    acquisition: CatalogAcquisition,
    *,
    changed_at: datetime | None = None,
) -> CatalogPersistenceResult:
    """Persist all available evidence before applying the catalog state transaction."""

    with session_factory() as session:
        with session.begin():
            for evidence in acquisition.evidence:
                persist_raw_evidence(session, evidence)

    return _persist_catalog_acquisition_transaction(
        session_factory,
        acquisition,
        changed_at=changed_at,
    )


def persist_catalog_acquisition(
    session_factory: sessionmaker[Session],
    acquisition: CatalogAcquisition,
    *,
    changed_at: datetime | None = None,
) -> tuple[PersistedProductRun, ...]:
    """M9-compatible catalog persistence API.

    M14 needs richer operational accounting, but M0-M13 callers historically
    receive only directly observed product results. Keep that public contract
    stable and expose the richer envelope through
    ``persist_catalog_acquisition_result``.
    """

    return persist_catalog_acquisition_result(
        session_factory,
        acquisition,
        changed_at=changed_at,
    ).observed_results


def persist_catalog_observations(
    session_factory: sessionmaker[Session],
    evidence: RawEvidence,
    observations: Iterable[ProductObservation],
    *,
    source: str,
    scope_key: str = "default",
    complete: bool,
    changed_at: datetime | None = None,
) -> tuple[PersistedProductRun, ...]:
    """M8 compatibility wrapper around the M9 coverage-proof persistence path.

    New catalog acquisition code must build a ``CatalogAcquisition`` and must not
    assert completeness with this boolean. The wrapper remains only so the M8
    acceptance contract can be replayed unchanged.
    """

    observations = tuple(observations)
    chunks: list[CatalogChunkResult] = [
        CatalogChunkResult(
            sequence=0,
            requested_ref=evidence.source_url,
            attempted_at=evidence.fetched_at,
            status=CatalogChunkStatus.SUCCESS,
            evidence=evidence,
            observations=observations,
            next_ref=None if complete else "legacy:coverage-unproven",
        )
    ]
    if not complete:
        chunks.append(
            CatalogChunkResult(
                sequence=1,
                requested_ref="legacy:coverage-unproven",
                attempted_at=evidence.fetched_at,
                status=CatalogChunkStatus.LEGACY_INCOMPLETE,
                error_code="M8_MANUAL_INCOMPLETE",
            )
        )

    acquisition = CatalogAcquisition(
        run_key=f"legacy:{source}:{scope_key}:{evidence.id}",
        source=source,
        scope_key=scope_key,
        start_ref=evidence.source_url,
        chunks=tuple(chunks),
    )
    return persist_catalog_acquisition(
        session_factory,
        acquisition,
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
