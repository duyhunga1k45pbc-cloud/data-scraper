from __future__ import annotations

from urllib.parse import urlsplit


SOURCE_BY_HOST = {
    "books.toscrape.com": "books_to_scrape",
    "scrapeme.live": "scrapeme_live",
}


class UnsupportedSourceError(ValueError):
    pass


def source_for_url(url: str) -> str:
    host = urlsplit(url).hostname
    source = SOURCE_BY_HOST.get(host or "")
    if source is None:
        raise UnsupportedSourceError(f"unsupported product source host: {host!r}")
    return source
