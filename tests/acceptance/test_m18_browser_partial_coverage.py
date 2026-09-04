from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.browser_acquisition.catalog import acquire_browser_catalog
from src.browser_acquisition.models import BrowserLoadError, BrowserPageSnapshot
from src.catalogs.models import CatalogChunkStatus, CatalogRunStatus

T0 = datetime(2026, 2, 1, tzinfo=timezone.utc)


def test_m18_two_rendered_pages_then_timeout_never_proves_complete():
    """The M18 stress case: useful partial work survives but absence is unproven."""

    def loader(ref: str) -> BrowserPageSnapshot:
        if ref == "dynamic:1":
            return BrowserPageSnapshot(
                requested_ref=ref,
                attempted_at=T0,
                final_url="https://fixture.test/catalog?page=1",
                status_code=200,
                content_type="text/html",
                body="<div data-product='A'></div>",
                next_ref="dynamic:2",
            )
        if ref == "dynamic:2":
            return BrowserPageSnapshot(
                requested_ref=ref,
                attempted_at=T0 + timedelta(seconds=1),
                final_url="https://fixture.test/catalog?page=2",
                status_code=200,
                content_type="text/html",
                body="<div data-product='B'></div>",
                next_ref="dynamic:3",
            )
        raise BrowserLoadError("BROWSER_TIMEOUT")

    def parser(evidence):
        if "A" in evidence.body:
            return ("A",)
        if "B" in evidence.body:
            return ("B",)
        return ()

    acquisition = acquire_browser_catalog(
        source="dynamic_fixture",
        scope_key="catalog",
        start_ref="dynamic:1",
        load_page=loader,
        parse_evidence=parser,
        run_key="m18-partial-browser-proof",
    )

    assert acquisition.coverage_status == CatalogRunStatus.INCOMPLETE
    assert acquisition.observations == ("A", "B")
    assert [chunk.status for chunk in acquisition.chunks] == [
        CatalogChunkStatus.SUCCESS,
        CatalogChunkStatus.SUCCESS,
        CatalogChunkStatus.FETCH_FAILED,
    ]
    assert [e.body for e in acquisition.evidence] == [
        "<div data-product='A'></div>",
        "<div data-product='B'></div>",
    ]
    assert acquisition.chunks[-1].evidence is None
