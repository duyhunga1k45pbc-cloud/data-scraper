from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

from src.acquisition.models import RawEvidence
from src.catalogs.models import (
    CatalogAcquisition,
    CatalogChunkResult,
    CatalogChunkStatus,
)

from .models import BrowserLoadError, BrowserPageSnapshot

PageLoader = Callable[[str], BrowserPageSnapshot]
EvidenceParser = Callable[[RawEvidence], Iterable[Any]]
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error_code(prefix: str, value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value)
    return f"{prefix}{cleaned}"[:128]


def _raw_evidence(snapshot: BrowserPageSnapshot) -> RawEvidence | None:
    if snapshot.status_code is None or snapshot.body is None:
        return None

    body_hash = hashlib.sha256(snapshot.body.encode("utf-8")).hexdigest()
    identity_material = "\0".join(
        (
            snapshot.requested_ref,
            snapshot.final_url or "",
            snapshot.attempted_at.isoformat(),
            str(snapshot.status_code),
            body_hash,
        )
    )
    evidence_id = hashlib.sha256(identity_material.encode("utf-8")).hexdigest()

    return RawEvidence(
        id=evidence_id,
        source_url=snapshot.final_url or snapshot.requested_ref,
        fetched_at=snapshot.attempted_at,
        status_code=snapshot.status_code,
        content_type=snapshot.content_type or "text/html",
        body=snapshot.body,
        body_hash=body_hash,
    )


def acquire_browser_catalog(
    *,
    source: str,
    scope_key: str,
    start_ref: str,
    load_page: PageLoader,
    parse_evidence: EvidenceParser,
    max_chunks: int = 50,
    run_key: str | None = None,
    clock: Clock = _utc_now,
) -> CatalogAcquisition:
    """Build an M9 ``CatalogAcquisition`` from browser-rendered pages.

    Browser mechanics stop at the evidence boundary. This function does not
    normalize, validate, persist product state, or assert catalog completeness.
    Existing ``CatalogAcquisition.coverage_status`` derives COMPLETE/INCOMPLETE
    from the emitted chunk proof.
    """

    if not source.strip():
        raise ValueError("source is required")
    if not scope_key.strip():
        raise ValueError("scope_key is required")
    if not start_ref.strip():
        raise ValueError("start_ref is required")
    if max_chunks < 1:
        raise ValueError("max_chunks must be >= 1")

    chunks: list[CatalogChunkResult] = []
    seen_refs: set[str] = set()
    current_ref: str | None = start_ref

    while current_ref is not None and len(chunks) < max_chunks:
        if current_ref in seen_refs:
            chunks.append(
                CatalogChunkResult(
                    sequence=len(chunks),
                    requested_ref=current_ref,
                    attempted_at=clock(),
                    status=CatalogChunkStatus.CYCLE_DETECTED,
                    error_code="BROWSER_CYCLE_DETECTED",
                )
            )
            current_ref = None
            break

        seen_refs.add(current_ref)
        attempted_at = clock()

        try:
            snapshot = load_page(current_ref)
        except BrowserLoadError as exc:
            snapshot = exc.snapshot
            evidence = _raw_evidence(snapshot) if snapshot is not None else None
            chunks.append(
                CatalogChunkResult(
                    sequence=len(chunks),
                    requested_ref=current_ref,
                    attempted_at=(snapshot.attempted_at if snapshot is not None else attempted_at),
                    status=CatalogChunkStatus.FETCH_FAILED,
                    evidence=evidence,
                    error_code=_safe_error_code("", exc.code),
                )
            )
            current_ref = None
            break
        except Exception as exc:
            chunks.append(
                CatalogChunkResult(
                    sequence=len(chunks),
                    requested_ref=current_ref,
                    attempted_at=attempted_at,
                    status=CatalogChunkStatus.FETCH_FAILED,
                    error_code=_safe_error_code("BROWSER_", type(exc).__name__),
                )
            )
            current_ref = None
            break

        evidence = _raw_evidence(snapshot)

        if snapshot.requested_ref != current_ref:
            chunks.append(
                CatalogChunkResult(
                    sequence=len(chunks),
                    requested_ref=current_ref,
                    attempted_at=snapshot.attempted_at,
                    status=CatalogChunkStatus.FETCH_FAILED,
                    evidence=evidence,
                    error_code="BROWSER_REQUEST_REF_MISMATCH",
                )
            )
            current_ref = None
            break

        if snapshot.error_code is not None:
            chunks.append(
                CatalogChunkResult(
                    sequence=len(chunks),
                    requested_ref=current_ref,
                    attempted_at=snapshot.attempted_at,
                    status=CatalogChunkStatus.FETCH_FAILED,
                    evidence=evidence,
                    error_code=_safe_error_code("", snapshot.error_code),
                )
            )
            current_ref = None
            break

        if snapshot.status_code is None or snapshot.body is None or evidence is None:
            chunks.append(
                CatalogChunkResult(
                    sequence=len(chunks),
                    requested_ref=current_ref,
                    attempted_at=snapshot.attempted_at,
                    status=CatalogChunkStatus.FETCH_FAILED,
                    error_code="BROWSER_NO_RENDERED_EVIDENCE",
                )
            )
            current_ref = None
            break

        if not 200 <= snapshot.status_code < 300:
            chunks.append(
                CatalogChunkResult(
                    sequence=len(chunks),
                    requested_ref=current_ref,
                    attempted_at=snapshot.attempted_at,
                    status=CatalogChunkStatus.HTTP_ERROR,
                    evidence=evidence,
                    error_code=f"HTTP_{snapshot.status_code}",
                )
            )
            current_ref = None
            break

        try:
            observations = tuple(parse_evidence(evidence))
        except Exception as exc:
            chunks.append(
                CatalogChunkResult(
                    sequence=len(chunks),
                    requested_ref=current_ref,
                    attempted_at=snapshot.attempted_at,
                    status=CatalogChunkStatus.PARSE_FAILED,
                    evidence=evidence,
                    error_code=_safe_error_code("PARSE_", type(exc).__name__),
                )
            )
            current_ref = None
            break

        chunks.append(
            CatalogChunkResult(
                sequence=len(chunks),
                requested_ref=current_ref,
                attempted_at=snapshot.attempted_at,
                status=CatalogChunkStatus.SUCCESS,
                evidence=evidence,
                observations=observations,
                next_ref=snapshot.next_ref,
            )
        )
        current_ref = snapshot.next_ref

    if current_ref is not None:
        # The previous successful chunk still points at this reference. Persist an
        # explicit terminal failure rather than silently truncating traversal.
        chunks.append(
            CatalogChunkResult(
                sequence=len(chunks),
                requested_ref=current_ref,
                attempted_at=clock(),
                status=CatalogChunkStatus.LIMIT_REACHED,
                error_code="BROWSER_MAX_CHUNKS_REACHED",
            )
        )

    return CatalogAcquisition(
        run_key=run_key or f"browser:{source}:{scope_key}:{uuid.uuid4().hex}",
        source=source,
        scope_key=scope_key,
        start_ref=start_ref,
        chunks=tuple(chunks),
    )
