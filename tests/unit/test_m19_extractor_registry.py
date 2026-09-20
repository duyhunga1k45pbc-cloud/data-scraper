from __future__ import annotations

from src.extractors.registry import resolve_extractor_runtime


def test_m19_version_addressable_runtime_is_explicitly_resolvable():
    runtime = resolve_extractor_runtime(source="web_scraping_dev", version="web-scraping-dev-html-v1")
    assert runtime is not None
    assert runtime.source == "web_scraping_dev"
    if hasattr(runtime, "extractor_version"):
        assert runtime.extractor_version == "web-scraping-dev-html-v1"
    if hasattr(runtime, "version"):
        assert runtime.version == "web-scraping-dev-html-v1"
