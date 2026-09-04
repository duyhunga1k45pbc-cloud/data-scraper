from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from src.acquisition.models import RawEvidence
from src.catalogs.acquisition import CatalogPageExtractionError, acquire_paginated_catalog
from src.catalogs.models import CatalogChunkStatus, CatalogPage, CatalogRunStatus


T0 = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)


def _evidence(ref: str, sequence: int, *, status: int = 200) -> RawEvidence:
    return RawEvidence.capture(
        evidence_id=f"m9-evidence-{sequence}",
        source_url=ref,
        fetched_at=T0 + timedelta(seconds=sequence),
        status_code=status,
        content_type="application/json",
        body=f'{{"page":{sequence}}}',
    )


def test_m9_complete_is_derived_from_contiguous_terminal_chunk_chain() -> None:
    refs = {
        "page:1": "page:2",
        "page:2": "page:3",
        "page:3": None,
    }

    def fetch(ref: str) -> RawEvidence:
        sequence = int(ref.split(":")[1])
        return _evidence(ref, sequence)

    def parse(evidence: RawEvidence) -> CatalogPage:
        return CatalogPage(observations=(), next_ref=refs[evidence.source_url])

    acquisition = acquire_paginated_catalog(
        source="scrapify_js",
        scope_key="m9-test",
        start_ref="page:1",
        fetch_page=fetch,
        parse_page=parse,
        run_key="m9-complete",
        now=lambda: T0,
    )

    assert acquisition.coverage_status == CatalogRunStatus.COMPLETE
    assert acquisition.terminal_reached is True
    assert [chunk.status for chunk in acquisition.chunks] == [
        CatalogChunkStatus.SUCCESS,
        CatalogChunkStatus.SUCCESS,
        CatalogChunkStatus.SUCCESS,
    ]
    assert [chunk.requested_ref for chunk in acquisition.chunks] == [
        "page:1",
        "page:2",
        "page:3",
    ]


def test_m9_transport_failure_makes_coverage_incomplete() -> None:
    def fetch(ref: str) -> RawEvidence:
        if ref == "page:2":
            request = httpx.Request("GET", "https://example.test/page/2")
            raise httpx.ConnectError("connection failed", request=request)
        return _evidence(ref, 1)

    def parse(_: RawEvidence) -> CatalogPage:
        return CatalogPage(observations=(), next_ref="page:2")

    acquisition = acquire_paginated_catalog(
        source="scrapify_js",
        scope_key="m9-test",
        start_ref="page:1",
        fetch_page=fetch,
        parse_page=parse,
        run_key="m9-fetch-failure",
        now=lambda: T0,
    )

    assert acquisition.coverage_status == CatalogRunStatus.INCOMPLETE
    assert [chunk.status for chunk in acquisition.chunks] == [
        CatalogChunkStatus.SUCCESS,
        CatalogChunkStatus.FETCH_FAILED,
    ]
    assert acquisition.chunks[-1].evidence is None


def test_m9_parse_failure_and_traversal_limit_cannot_claim_complete() -> None:
    def fetch(ref: str) -> RawEvidence:
        return _evidence(ref, len(ref))

    def broken_parse(_: RawEvidence) -> CatalogPage:
        raise CatalogPageExtractionError("PAGE_SCHEMA_INVALID")

    broken = acquire_paginated_catalog(
        source="scrapify_js",
        scope_key="m9-test",
        start_ref="page:1",
        fetch_page=fetch,
        parse_page=broken_parse,
        run_key="m9-parse-failure",
        now=lambda: T0,
    )
    assert broken.coverage_status == CatalogRunStatus.INCOMPLETE
    assert broken.chunks[-1].status == CatalogChunkStatus.PARSE_FAILED
    assert broken.chunks[-1].evidence is not None

    limited = acquire_paginated_catalog(
        source="scrapify_js",
        scope_key="m9-test",
        start_ref="page:1",
        fetch_page=fetch,
        parse_page=lambda _: CatalogPage(observations=(), next_ref="page:2"),
        run_key="m9-limit",
        max_chunks=1,
        now=lambda: T0,
    )
    assert limited.coverage_status == CatalogRunStatus.INCOMPLETE
    assert [chunk.status for chunk in limited.chunks] == [
        CatalogChunkStatus.SUCCESS,
        CatalogChunkStatus.LIMIT_REACHED,
    ]


def test_m9_cycle_or_broken_continuation_chain_is_incomplete() -> None:
    def fetch(ref: str) -> RawEvidence:
        return _evidence(ref, 1)

    cycle = acquire_paginated_catalog(
        source="scrapify_js",
        scope_key="m9-test",
        start_ref="page:1",
        fetch_page=fetch,
        parse_page=lambda _: CatalogPage(observations=(), next_ref="page:1"),
        run_key="m9-cycle",
        now=lambda: T0,
    )
    assert cycle.coverage_status == CatalogRunStatus.INCOMPLETE
    assert cycle.chunks[-1].status == CatalogChunkStatus.CYCLE_DETECTED

    from src.catalogs.models import CatalogAcquisition, CatalogChunkResult

    gap = CatalogAcquisition(
        run_key="m9-gap",
        source="scrapify_js",
        scope_key="m9-test",
        start_ref="page:1",
        chunks=(
            CatalogChunkResult(
                sequence=0,
                requested_ref="page:1",
                attempted_at=T0,
                status=CatalogChunkStatus.SUCCESS,
                evidence=_evidence("page:1", 1),
                next_ref="page:2",
            ),
            CatalogChunkResult(
                sequence=1,
                requested_ref="page:3",
                attempted_at=T0,
                status=CatalogChunkStatus.SUCCESS,
                evidence=_evidence("page:3", 3),
                next_ref=None,
            ),
        ),
    )
    assert gap.coverage_status == CatalogRunStatus.INCOMPLETE
