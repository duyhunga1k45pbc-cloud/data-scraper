from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from src.acquisition.models import RawEvidence
from src.catalogs.models import CatalogAcquisition, CatalogChunkResult, CatalogChunkStatus

from .parser import HOST, SOURCE, WebScrapingDevParseError, parse_product_evidence

CATALOG_START = "https://web-scraping.dev/products?page=1"
_PRODUCT_PATH = re.compile(r"^/product/\d+/?$")


@dataclass(frozen=True)
class HttpPageSnapshot:
    requested_ref: str
    attempted_at: datetime
    final_url: str | None
    status_code: int | None
    content_type: str | None
    body: str | None


class HttpPageLoadError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class CatalogPageDiscovery:
    product_urls: tuple[str, ...]
    next_catalog_url: str | None


class HttpxPageLoader:
    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        self.timeout_seconds = timeout_seconds

    def __call__(self, ref: str) -> HttpPageSnapshot:
        attempted_at = datetime.now(timezone.utc)
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=self.timeout_seconds,
                headers={"User-Agent": "data-scraper-m19/0.17 (+safe public scraping test)"},
            ) as client:
                response = client.get(ref)
        except httpx.TimeoutException as exc:
            raise HttpPageLoadError("HTTP_TIMEOUT", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HttpPageLoadError("HTTP_TRANSPORT_ERROR", str(exc)) from exc

        return HttpPageSnapshot(
            requested_ref=ref,
            attempted_at=attempted_at,
            final_url=str(response.url),
            status_code=response.status_code,
            content_type=response.headers.get("content-type", "text/html"),
            body=response.text,
        )


def _canonical_ref(base: str, href: str) -> str | None:
    absolute = urljoin(base, href)
    parsed = urlsplit(absolute)
    if parsed.scheme not in {"http", "https"} or parsed.hostname != HOST:
        return None
    return urlunsplit(("https", HOST, parsed.path, parsed.query, ""))


def _page_number(url: str) -> int | None:
    parsed = urlsplit(url)
    if parsed.hostname != HOST or parsed.path.rstrip("/") != "/products":
        return None
    values = parse_qs(parsed.query).get("page")
    if not values:
        return 1
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return None


def discover_catalog_page(body: str, source_url: str) -> CatalogPageDiscovery:
    soup = BeautifulSoup(body, "lxml")
    product_urls: list[str] = []
    seen_products: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        absolute = _canonical_ref(source_url, str(anchor["href"]))
        if absolute is None:
            continue
        parsed = urlsplit(absolute)
        if not _PRODUCT_PATH.fullmatch(parsed.path):
            continue
        canonical = urlunsplit(("https", HOST, parsed.path.rstrip("/"), "", ""))
        if canonical not in seen_products:
            seen_products.add(canonical)
            product_urls.append(canonical)

    # A catalog page that no longer exposes any product links is treated as a
    # parser failure, not as proof that the whole catalog is empty. This avoids a
    # site-layout change silently becoming a mass DISAPPEARED event.
    if not product_urls:
        raise WebScrapingDevParseError("WEB_SCRAPING_DEV_CATALOG_NO_PRODUCT_LINKS")

    current_page = _page_number(source_url) or 1
    candidates: list[tuple[int, str]] = []
    for anchor in soup.find_all("a", href=True):
        absolute = _canonical_ref(source_url, str(anchor["href"]))
        if absolute is None:
            continue
        page = _page_number(absolute)
        if page is not None and page > current_page:
            candidates.append((page, absolute))

    next_catalog = min(candidates, default=(0, None), key=lambda item: item[0])[1]
    return CatalogPageDiscovery(tuple(product_urls), next_catalog)


def raw_evidence_from_snapshot(snapshot: HttpPageSnapshot) -> RawEvidence | None:
    if snapshot.status_code is None or snapshot.body is None:
        return None
    body_hash = hashlib.sha256(snapshot.body.encode("utf-8")).hexdigest()
    material = "\0".join(
        (
            snapshot.requested_ref,
            snapshot.final_url or "",
            snapshot.attempted_at.isoformat(),
            str(snapshot.status_code),
            body_hash,
        )
    )
    evidence_id = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return RawEvidence(
        id=evidence_id,
        source_url=snapshot.final_url or snapshot.requested_ref,
        fetched_at=snapshot.attempted_at,
        status_code=snapshot.status_code,
        content_type=snapshot.content_type or "text/html",
        body=snapshot.body,
        body_hash=body_hash,
    )


def _error_code(prefix: str, value: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value)
    return (prefix + clean)[:128]


def acquire_web_scraping_dev_catalog(
    *,
    start_ref: str = CATALOG_START,
    scope_key: str = "products",
    load_page: Callable[[str], HttpPageSnapshot] | None = None,
    max_catalog_pages: int = 20,
    max_products: int = 200,
    run_key: str | None = None,
) -> CatalogAcquisition:
    """Acquire web-scraping.dev into the existing M9 proof contract.

    Catalog discovery pages and product-detail pages form one linear chunk proof.
    Any HTTP/transport/parse failure or configured traversal limit ends in an
    explicit failure chunk, so the run remains INCOMPLETE and cannot prove
    product absence.
    """

    if max_catalog_pages < 1:
        raise ValueError("max_catalog_pages must be >= 1")
    if max_products < 1:
        raise ValueError("max_products must be >= 1")
    parsed_start = urlsplit(start_ref)
    if parsed_start.hostname != HOST or parsed_start.path.rstrip("/") != "/products":
        raise ValueError("start_ref must be a web-scraping.dev /products URL")

    loader = load_page or HttpxPageLoader()
    chunks: list[CatalogChunkResult] = []
    discovered_products: list[str] = []
    seen_products: set[str] = set()
    seen_catalog_refs: set[str] = set()
    current_catalog: str | None = start_ref
    terminal_catalog_chunk_index: int | None = None

    def append_failure(
        *, ref: str, attempted_at: datetime, status: CatalogChunkStatus,
        evidence: RawEvidence | None = None, error_code: str,
    ) -> None:
        chunks.append(
            CatalogChunkResult(
                sequence=len(chunks), requested_ref=ref, attempted_at=attempted_at,
                status=status, evidence=evidence, error_code=error_code,
            )
        )

    while current_catalog is not None:
        if current_catalog in seen_catalog_refs:
            append_failure(
                ref=current_catalog,
                attempted_at=datetime.now(timezone.utc),
                status=CatalogChunkStatus.CYCLE_DETECTED,
                error_code="WEB_SCRAPING_DEV_CATALOG_CYCLE",
            )
            current_catalog = None
            break
        if len(seen_catalog_refs) >= max_catalog_pages:
            append_failure(
                ref=current_catalog,
                attempted_at=datetime.now(timezone.utc),
                status=CatalogChunkStatus.LIMIT_REACHED,
                error_code="WEB_SCRAPING_DEV_CATALOG_PAGE_LIMIT",
            )
            current_catalog = None
            break

        seen_catalog_refs.add(current_catalog)
        attempted_at = datetime.now(timezone.utc)
        try:
            snapshot = loader(current_catalog)
        except HttpPageLoadError as exc:
            append_failure(
                ref=current_catalog, attempted_at=attempted_at,
                status=CatalogChunkStatus.FETCH_FAILED,
                error_code=_error_code("", exc.code),
            )
            current_catalog = None
            break
        except Exception as exc:
            append_failure(
                ref=current_catalog, attempted_at=attempted_at,
                status=CatalogChunkStatus.FETCH_FAILED,
                error_code=_error_code("HTTP_", type(exc).__name__),
            )
            current_catalog = None
            break

        evidence = raw_evidence_from_snapshot(snapshot)
        if snapshot.requested_ref != current_catalog:
            append_failure(
                ref=current_catalog, attempted_at=snapshot.attempted_at,
                status=CatalogChunkStatus.FETCH_FAILED, evidence=evidence,
                error_code="WEB_SCRAPING_DEV_REQUEST_REF_MISMATCH",
            )
            current_catalog = None
            break
        if evidence is None or snapshot.status_code is None or snapshot.body is None:
            append_failure(
                ref=current_catalog, attempted_at=snapshot.attempted_at,
                status=CatalogChunkStatus.FETCH_FAILED, evidence=evidence,
                error_code="WEB_SCRAPING_DEV_EMPTY_RESPONSE",
            )
            current_catalog = None
            break
        if snapshot.status_code < 200 or snapshot.status_code >= 300:
            append_failure(
                ref=current_catalog, attempted_at=snapshot.attempted_at,
                status=CatalogChunkStatus.HTTP_ERROR, evidence=evidence,
                error_code=f"HTTP_{snapshot.status_code}",
            )
            current_catalog = None
            break

        try:
            discovery = discover_catalog_page(snapshot.body, evidence.source_url)
        except Exception as exc:
            append_failure(
                ref=current_catalog, attempted_at=snapshot.attempted_at,
                status=CatalogChunkStatus.PARSE_FAILED, evidence=evidence,
                error_code=_error_code("PARSE_", getattr(exc, "args", [type(exc).__name__])[0] or type(exc).__name__),
            )
            current_catalog = None
            break

        for url in discovery.product_urls:
            if url not in seen_products:
                seen_products.add(url)
                discovered_products.append(url)

        chunks.append(
            CatalogChunkResult(
                sequence=len(chunks), requested_ref=current_catalog,
                attempted_at=snapshot.attempted_at, status=CatalogChunkStatus.SUCCESS,
                evidence=evidence, observations=(), next_ref=discovery.next_catalog_url,
            )
        )
        terminal_catalog_chunk_index = len(chunks) - 1
        current_catalog = discovery.next_catalog_url

    # If catalog traversal already ended in failure, preserve that proof exactly;
    # directly discovered product URLs are not fetched after the gap because the
    # proof chain can no longer remain linear from start_ref.
    if not chunks or chunks[-1].status != CatalogChunkStatus.SUCCESS or current_catalog is not None:
        return CatalogAcquisition(
            run_key=run_key or f"m19:{uuid.uuid4().hex}",
            source=SOURCE, scope_key=scope_key, start_ref=start_ref, chunks=tuple(chunks),
        )

    assert terminal_catalog_chunk_index is not None
    if not discovered_products:
        # Defensive: discover_catalog_page already rejects this case.
        append_failure(
            ref=start_ref, attempted_at=datetime.now(timezone.utc),
            status=CatalogChunkStatus.PARSE_FAILED,
            error_code="WEB_SCRAPING_DEV_NO_PRODUCTS_DISCOVERED",
        )
        return CatalogAcquisition(
            run_key=run_key or f"m19:{uuid.uuid4().hex}",
            source=SOURCE, scope_key=scope_key, start_ref=start_ref, chunks=tuple(chunks),
        )

    product_limit_hit = len(discovered_products) > max_products
    selected_products = discovered_products[:max_products]
    first_product = selected_products[0]
    terminal_catalog = chunks[terminal_catalog_chunk_index]
    chunks[terminal_catalog_chunk_index] = CatalogChunkResult(
        sequence=terminal_catalog.sequence,
        requested_ref=terminal_catalog.requested_ref,
        attempted_at=terminal_catalog.attempted_at,
        status=terminal_catalog.status,
        evidence=terminal_catalog.evidence,
        observations=terminal_catalog.observations,
        next_ref=first_product,
        error_code=terminal_catalog.error_code,
    )

    for index, product_url in enumerate(selected_products):
        attempted_at = datetime.now(timezone.utc)
        try:
            snapshot = loader(product_url)
        except HttpPageLoadError as exc:
            append_failure(
                ref=product_url, attempted_at=attempted_at,
                status=CatalogChunkStatus.FETCH_FAILED,
                error_code=_error_code("", exc.code),
            )
            break
        except Exception as exc:
            append_failure(
                ref=product_url, attempted_at=attempted_at,
                status=CatalogChunkStatus.FETCH_FAILED,
                error_code=_error_code("HTTP_", type(exc).__name__),
            )
            break

        evidence = raw_evidence_from_snapshot(snapshot)
        if snapshot.requested_ref != product_url:
            append_failure(
                ref=product_url, attempted_at=snapshot.attempted_at,
                status=CatalogChunkStatus.FETCH_FAILED, evidence=evidence,
                error_code="WEB_SCRAPING_DEV_REQUEST_REF_MISMATCH",
            )
            break
        if evidence is None or snapshot.status_code is None or snapshot.body is None:
            append_failure(
                ref=product_url, attempted_at=snapshot.attempted_at,
                status=CatalogChunkStatus.FETCH_FAILED, evidence=evidence,
                error_code="WEB_SCRAPING_DEV_EMPTY_RESPONSE",
            )
            break
        if snapshot.status_code < 200 or snapshot.status_code >= 300:
            append_failure(
                ref=product_url, attempted_at=snapshot.attempted_at,
                status=CatalogChunkStatus.HTTP_ERROR, evidence=evidence,
                error_code=f"HTTP_{snapshot.status_code}",
            )
            break

        try:
            observations = parse_product_evidence(evidence)
        except Exception as exc:
            append_failure(
                ref=product_url, attempted_at=snapshot.attempted_at,
                status=CatalogChunkStatus.PARSE_FAILED, evidence=evidence,
                error_code=_error_code("PARSE_", getattr(exc, "args", [type(exc).__name__])[0] or type(exc).__name__),
            )
            break

        if index + 1 < len(selected_products):
            next_ref = selected_products[index + 1]
        elif product_limit_hit:
            next_ref = discovered_products[max_products]
        else:
            next_ref = None

        chunks.append(
            CatalogChunkResult(
                sequence=len(chunks), requested_ref=product_url,
                attempted_at=snapshot.attempted_at, status=CatalogChunkStatus.SUCCESS,
                evidence=evidence, observations=observations, next_ref=next_ref,
            )
        )

    if product_limit_hit and chunks[-1].status == CatalogChunkStatus.SUCCESS:
        omitted = discovered_products[max_products]
        append_failure(
            ref=omitted, attempted_at=datetime.now(timezone.utc),
            status=CatalogChunkStatus.LIMIT_REACHED,
            error_code="WEB_SCRAPING_DEV_PRODUCT_LIMIT",
        )

    return CatalogAcquisition(
        run_key=run_key or f"m19:{uuid.uuid4().hex}",
        source=SOURCE, scope_key=scope_key, start_ref=start_ref, chunks=tuple(chunks),
    )
