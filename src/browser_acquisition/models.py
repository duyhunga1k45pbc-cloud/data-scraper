from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BrowserPageSnapshot:
    """One browser acquisition attempt at a catalog reference.

    ``body`` is the exact rendered DOM snapshot handed to the parser. It is an
    acquisition artifact, not a claim that the original HTTP response bytes and
    the rendered DOM are identical.
    """

    requested_ref: str
    attempted_at: datetime
    final_url: str | None
    status_code: int | None
    content_type: str | None
    body: str | None
    next_ref: str | None
    error_code: str | None = None


@dataclass(frozen=True)
class RenderedPageCapture:
    """Initial navigation body plus the post-JavaScript rendered DOM."""

    snapshot: BrowserPageSnapshot
    initial_body: str | None


@dataclass(frozen=True)
class JsLinkProbeResult:
    requested_url: str
    final_url: str | None
    status_code: int | None
    initial_hrefs: tuple[str, ...]
    rendered_hrefs: tuple[str, ...]
    added_hrefs: tuple[str, ...]

    @property
    def js_added_links(self) -> bool:
        return bool(self.added_hrefs)


class BrowserLoadError(RuntimeError):
    """Browser/navigation/action failure with optional captured evidence."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        snapshot: BrowserPageSnapshot | None = None,
    ) -> None:
        self.code = code
        self.snapshot = snapshot
        super().__init__(message or code)
