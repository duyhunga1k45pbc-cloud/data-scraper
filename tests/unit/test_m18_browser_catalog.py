from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.browser_acquisition.catalog import acquire_browser_catalog
from src.browser_acquisition.models import BrowserLoadError, BrowserPageSnapshot
from src.catalogs.models import CatalogChunkStatus, CatalogRunStatus

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _snapshot(ref: str, *, body: str, next_ref: str | None, status: int = 200, n: int = 0):
    return BrowserPageSnapshot(
        requested_ref=ref,
        attempted_at=T0 + timedelta(seconds=n),
        final_url=ref,
        status_code=status,
        content_type="text/html; charset=utf-8",
        body=body,
        next_ref=next_ref,
    )


def _parser(evidence):
    return (f"obs:{evidence.id}",)


def test_m18_complete_browser_chain_is_derived_complete():
    pages = {
        "page:1": _snapshot("page:1", body="<p>one</p>", next_ref="page:2", n=1),
        "page:2": _snapshot("page:2", body="<p>two</p>", next_ref=None, n=2),
    }
    acquisition = acquire_browser_catalog(
        source="browser_fixture",
        scope_key="default",
        start_ref="page:1",
        load_page=pages.__getitem__,
        parse_evidence=_parser,
        run_key="m18-complete",
    )

    assert acquisition.coverage_status == CatalogRunStatus.COMPLETE
    assert [chunk.status for chunk in acquisition.chunks] == [
        CatalogChunkStatus.SUCCESS,
        CatalogChunkStatus.SUCCESS,
    ]
    assert len(acquisition.evidence) == 2
    assert len(acquisition.observations) == 2
    assert all(item.body_hash for item in acquisition.evidence)


def test_m18_transport_failure_has_no_fabricated_evidence():
    def loader(ref: str):
        if ref == "page:1":
            return _snapshot("page:1", body="<p>one</p>", next_ref="page:2", n=1)
        raise BrowserLoadError("BROWSER_TIMEOUT")

    acquisition = acquire_browser_catalog(
        source="browser_fixture",
        scope_key="default",
        start_ref="page:1",
        load_page=loader,
        parse_evidence=_parser,
        run_key="m18-timeout",
    )

    assert acquisition.coverage_status == CatalogRunStatus.INCOMPLETE
    assert [chunk.status for chunk in acquisition.chunks] == [
        CatalogChunkStatus.SUCCESS,
        CatalogChunkStatus.FETCH_FAILED,
    ]
    assert acquisition.chunks[1].evidence is None
    assert len(acquisition.evidence) == 1
    assert len(acquisition.observations) == 1


def test_m18_http_error_preserves_received_browser_evidence():
    page = _snapshot("page:1", body="rate limited", next_ref=None, status=429, n=1)
    acquisition = acquire_browser_catalog(
        source="browser_fixture",
        scope_key="default",
        start_ref="page:1",
        load_page=lambda _: page,
        parse_evidence=_parser,
        run_key="m18-http",
    )

    assert acquisition.coverage_status == CatalogRunStatus.INCOMPLETE
    assert acquisition.chunks[0].status == CatalogChunkStatus.HTTP_ERROR
    assert acquisition.chunks[0].evidence is not None
    assert acquisition.chunks[0].error_code == "HTTP_429"


def test_m18_parse_failure_preserves_rendered_dom_evidence():
    page = _snapshot("page:1", body="<div>rendered</div>", next_ref=None, n=1)

    def broken_parser(_):
        raise ValueError("fixture parse failure")

    acquisition = acquire_browser_catalog(
        source="browser_fixture",
        scope_key="default",
        start_ref="page:1",
        load_page=lambda _: page,
        parse_evidence=broken_parser,
        run_key="m18-parse",
    )

    assert acquisition.coverage_status == CatalogRunStatus.INCOMPLETE
    assert acquisition.chunks[0].status == CatalogChunkStatus.PARSE_FAILED
    assert acquisition.chunks[0].evidence is not None
    assert acquisition.chunks[0].evidence.body == "<div>rendered</div>"


def test_m18_cycle_and_limit_are_explicit_incomplete_chunks():
    cycle_pages = {
        "page:1": _snapshot("page:1", body="1", next_ref="page:2", n=1),
        "page:2": _snapshot("page:2", body="2", next_ref="page:1", n=2),
    }
    cycle = acquire_browser_catalog(
        source="browser_fixture",
        scope_key="default",
        start_ref="page:1",
        load_page=cycle_pages.__getitem__,
        parse_evidence=_parser,
        run_key="m18-cycle",
    )
    assert cycle.coverage_status == CatalogRunStatus.INCOMPLETE
    assert cycle.chunks[-1].status == CatalogChunkStatus.CYCLE_DETECTED

    limit_pages = {
        "page:1": _snapshot("page:1", body="1", next_ref="page:2", n=1),
        "page:2": _snapshot("page:2", body="2", next_ref="page:3", n=2),
    }
    limited = acquire_browser_catalog(
        source="browser_fixture",
        scope_key="default",
        start_ref="page:1",
        load_page=limit_pages.__getitem__,
        parse_evidence=_parser,
        max_chunks=2,
        run_key="m18-limit",
    )
    assert limited.coverage_status == CatalogRunStatus.INCOMPLETE
    assert limited.chunks[-1].status == CatalogChunkStatus.LIMIT_REACHED
    assert limited.chunks[-1].requested_ref == "page:3"
