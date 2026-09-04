from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .models import BrowserLoadError, BrowserPageSnapshot, RenderedPageCapture

NextRefResolver = Callable[[str, str], str | None]
PageAction = Callable[[Any], None]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ChromiumSession:
    """Thin Playwright Chromium session used only by acquisition code."""

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = 15_000,
        settle_ms: int = 250,
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.settle_ms = settle_ms
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self) -> "ChromiumSession":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - dependency/setup guard
            raise RuntimeError(
                "Playwright is not installed. Run `pip install -e .` first."
            ) from exc

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    @property
    def page(self):
        if self._page is None:
            raise RuntimeError("ChromiumSession must be used as a context manager")
        return self._page

    def render(
        self,
        requested_ref: str,
        *,
        after_load: PageAction | None = None,
        next_ref_resolver: NextRefResolver | None = None,
    ) -> RenderedPageCapture:
        page = self.page
        attempted_at = _utc_now()

        try:
            response = page.goto(
                requested_ref,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
        except Exception as exc:
            raise BrowserLoadError(
                "BROWSER_NAVIGATION_FAILED",
                f"{type(exc).__name__}: {exc}",
            ) from exc

        if response is None:
            raise BrowserLoadError("BROWSER_NO_NAVIGATION_RESPONSE")

        status_code = response.status
        content_type = response.headers.get("content-type") or "text/html"
        final_url = page.url

        initial_body: str | None
        try:
            initial_body = response.text()
        except Exception:
            initial_body = None

        if self.settle_ms > 0:
            page.wait_for_timeout(self.settle_ms)

        if after_load is not None:
            try:
                after_load(page)
            except Exception as exc:
                body = None
                try:
                    body = page.content()
                except Exception:
                    pass
                snapshot = BrowserPageSnapshot(
                    requested_ref=requested_ref,
                    attempted_at=attempted_at,
                    final_url=final_url,
                    status_code=status_code,
                    content_type=content_type,
                    body=body,
                    next_ref=None,
                    error_code="BROWSER_ACTION_FAILED",
                )
                raise BrowserLoadError(
                    "BROWSER_ACTION_FAILED",
                    f"{type(exc).__name__}: {exc}",
                    snapshot=snapshot,
                ) from exc

        try:
            body = page.content()
        except Exception as exc:
            raise BrowserLoadError(
                "BROWSER_RENDER_CAPTURE_FAILED",
                f"{type(exc).__name__}: {exc}",
            ) from exc

        next_ref = None
        if next_ref_resolver is not None:
            try:
                next_ref = next_ref_resolver(final_url, body)
            except Exception as exc:
                snapshot = BrowserPageSnapshot(
                    requested_ref=requested_ref,
                    attempted_at=attempted_at,
                    final_url=final_url,
                    status_code=status_code,
                    content_type=content_type,
                    body=body,
                    next_ref=None,
                    error_code="BROWSER_NEXT_REF_FAILED",
                )
                raise BrowserLoadError(
                    "BROWSER_NEXT_REF_FAILED",
                    f"{type(exc).__name__}: {exc}",
                    snapshot=snapshot,
                ) from exc

        snapshot = BrowserPageSnapshot(
            requested_ref=requested_ref,
            attempted_at=attempted_at,
            final_url=final_url,
            status_code=status_code,
            content_type=content_type,
            body=body,
            next_ref=next_ref,
        )
        return RenderedPageCapture(snapshot=snapshot, initial_body=initial_body)

    def load(
        self,
        requested_ref: str,
        *,
        after_load: PageAction | None = None,
        next_ref_resolver: NextRefResolver | None = None,
    ) -> BrowserPageSnapshot:
        return self.render(
            requested_ref,
            after_load=after_load,
            next_ref_resolver=next_ref_resolver,
        ).snapshot
