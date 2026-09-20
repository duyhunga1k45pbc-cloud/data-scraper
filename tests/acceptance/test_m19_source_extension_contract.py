from __future__ import annotations

from pathlib import Path


def test_m19_source_adapter_does_not_create_a_second_trusted_state_pipeline():
    files = [
        Path("src/web_scraping_dev/parser.py"),
        Path("src/web_scraping_dev/acquisition.py"),
        Path("src/extractors/web_scraping_dev_html_v1.py"),
    ]
    forbidden = (
        "src.products.state",
        "src.storage.replay",
        "src.storage.rebuild",
        "src.runs.service",
        "ProductHistoryRow",
        "ProductRow",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for token in forbidden:
        assert token not in combined


def test_m19_core_files_are_not_m19_source_specific():
    # The source extension is allowed to register source validity and an M11
    # extractor runtime, but product-state/replay/rebuild/run logic stays generic.
    for path in (
        Path("src/products/state.py"),
        Path("src/storage/replay.py"),
        Path("src/storage/rebuild.py"),
        Path("src/runs/service.py"),
    ):
        assert "web_scraping_dev" not in path.read_text(encoding="utf-8")
        assert "web-scraping.dev" not in path.read_text(encoding="utf-8")
