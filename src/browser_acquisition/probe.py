from __future__ import annotations

from html.parser import HTMLParser

from .models import JsLinkProbeResult
from .playwright_driver import ChromiumSession


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(str(value))


def _hrefs(body: str | None) -> tuple[str, ...]:
    if not body:
        return ()
    parser = _HrefParser()
    parser.feed(body)
    return tuple(parser.hrefs)


def probe_js_link_discovery(
    url: str,
    *,
    timeout_ms: int = 15_000,
    settle_ms: int = 500,
    headless: bool = True,
) -> JsLinkProbeResult:
    """Compare initial navigation HTML with the post-JavaScript DOM."""

    with ChromiumSession(
        headless=headless,
        timeout_ms=timeout_ms,
        settle_ms=settle_ms,
    ) as browser:
        capture = browser.render(url)

    initial = _hrefs(capture.initial_body)
    rendered = _hrefs(capture.snapshot.body)
    initial_set = set(initial)
    added = tuple(href for href in rendered if href not in initial_set)

    return JsLinkProbeResult(
        requested_url=url,
        final_url=capture.snapshot.final_url,
        status_code=capture.snapshot.status_code,
        initial_hrefs=initial,
        rendered_hrefs=rendered,
        added_hrefs=added,
    )
