from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

import httpx

from src.acquisition.models import RawEvidence
from src.products.models import ProductObservation

from .models import (
    CatalogAcquisition,
    CatalogChunkResult,
    CatalogChunkStatus,
    CatalogPage,
)


class CatalogPageExtractionError(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def acquire_paginated_catalog(
    *,
    source: str,
    scope_key: str,
    start_ref: str,
    fetch_page: Callable[[str], RawEvidence],
    parse_page: Callable[[RawEvidence], CatalogPage],
    run_key: str | None = None,
    max_chunks: int = 100,
    now: Callable[[], datetime] = _utc_now,
) -> CatalogAcquisition:
    """Traverse a paginated scope and derive coverage from acquisition evidence.

    The function deliberately returns an INCOMPLETE acquisition on HTTP,
    transport, parse, cycle, or traversal-limit failure. Successful chunks and
    their exact RawEvidence remain available for persistence/audit.
    """

    if max_chunks < 1:
        raise ValueError("max_chunks must be >= 1")

    chunks: list[CatalogChunkResult] = []
    current_ref = start_ref
    seen_refs: set[str] = set()

    while current_ref is not None:
        sequence = len(chunks)
        if current_ref in seen_refs:
            chunks.append(
                CatalogChunkResult(
                    sequence=sequence,
                    requested_ref=current_ref,
                    attempted_at=now(),
                    status=CatalogChunkStatus.CYCLE_DETECTED,
                    error_code="PAGINATION_CYCLE",
                )
            )
            break

        if sequence >= max_chunks:
            chunks.append(
                CatalogChunkResult(
                    sequence=sequence,
                    requested_ref=current_ref,
                    attempted_at=now(),
                    status=CatalogChunkStatus.LIMIT_REACHED,
                    error_code="MAX_CHUNKS_REACHED",
                )
            )
            break

        seen_refs.add(current_ref)
        attempted_at = now()
        try:
            evidence = fetch_page(current_ref)
        except httpx.RequestError as exc:
            chunks.append(
                CatalogChunkResult(
                    sequence=sequence,
                    requested_ref=current_ref,
                    attempted_at=attempted_at,
                    status=CatalogChunkStatus.FETCH_FAILED,
                    error_code=type(exc).__name__,
                )
            )
            break

        if not 200 <= evidence.status_code < 300:
            chunks.append(
                CatalogChunkResult(
                    sequence=sequence,
                    requested_ref=current_ref,
                    attempted_at=attempted_at,
                    status=CatalogChunkStatus.HTTP_ERROR,
                    evidence=evidence,
                    error_code=f"HTTP_{evidence.status_code}",
                )
            )
            break

        try:
            page = parse_page(evidence)
        except (CatalogPageExtractionError, ValueError) as exc:
            chunks.append(
                CatalogChunkResult(
                    sequence=sequence,
                    requested_ref=current_ref,
                    attempted_at=attempted_at,
                    status=CatalogChunkStatus.PARSE_FAILED,
                    evidence=evidence,
                    error_code=str(exc) or type(exc).__name__,
                )
            )
            break

        chunks.append(
            CatalogChunkResult(
                sequence=sequence,
                requested_ref=current_ref,
                attempted_at=attempted_at,
                status=CatalogChunkStatus.SUCCESS,
                evidence=evidence,
                observations=page.observations,
                next_ref=page.next_ref,
            )
        )
        current_ref = page.next_ref

    return CatalogAcquisition(
        run_key=run_key or str(uuid4()),
        source=source,
        scope_key=scope_key,
        start_ref=start_ref,
        chunks=tuple(chunks),
    )


def single_payload_catalog_acquisition(
    *,
    source: str,
    scope_key: str,
    evidence: RawEvidence,
    observations: tuple[ProductObservation, ...],
    run_key: str | None = None,
) -> CatalogAcquisition:
    """Build a proven one-chunk catalog for a source-defined full payload.

    The configured endpoint itself is the scope boundary: a successful parsed
    payload has no continuation, so the chunk's next_ref is evidence-backed as
    terminal for that source contract. No caller-supplied COMPLETE flag exists.
    """

    chunk = CatalogChunkResult(
        sequence=0,
        requested_ref=evidence.source_url,
        attempted_at=evidence.fetched_at,
        status=CatalogChunkStatus.SUCCESS,
        evidence=evidence,
        observations=tuple(observations),
        next_ref=None,
    )
    return CatalogAcquisition(
        run_key=run_key or str(uuid4()),
        source=source,
        scope_key=scope_key,
        start_ref=evidence.source_url,
        chunks=(chunk,),
    )
