from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.acquisition.models import RawEvidence
from src.products.models import ProductObservation

from . import books_to_scrape_v1
from . import scrapeme_live_v2
from . import scrapify_js_json_v1
from . import scraping_sandbox_json_v1


ExtractorCallable = Callable[[RawEvidence], tuple[ProductObservation, ...]]


class ExtractorRuntimeNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class ExtractorRuntime:
    source: str
    version: str
    implementation: str
    extract: ExtractorCallable


def _single(parser: Callable[[RawEvidence], ProductObservation]) -> ExtractorCallable:
    def extract(evidence: RawEvidence) -> tuple[ProductObservation, ...]:
        return (parser(evidence),)

    return extract


_RUNTIMES = (
    ExtractorRuntime(
        source=books_to_scrape_v1.SOURCE,
        version=books_to_scrape_v1.EXTRACTOR_VERSION,
        implementation="src.extractors.books_to_scrape_v1:parse_book",
        extract=_single(books_to_scrape_v1.parse_book),
    ),
    ExtractorRuntime(
        source=scrapeme_live_v2.SOURCE,
        version=scrapeme_live_v2.EXTRACTOR_VERSION,
        implementation="src.extractors.scrapeme_live_v2:parse_product",
        extract=_single(scrapeme_live_v2.parse_product),
    ),
    ExtractorRuntime(
        source=scrapify_js_json_v1.SOURCE,
        version=scrapify_js_json_v1.EXTRACTOR_VERSION,
        implementation="src.extractors.scrapify_js_json_v1:parse_catalog",
        extract=scrapify_js_json_v1.parse_catalog,
    ),
    ExtractorRuntime(
        source=scraping_sandbox_json_v1.SOURCE,
        version=scraping_sandbox_json_v1.EXTRACTOR_VERSION,
        implementation="src.extractors.scraping_sandbox_json_v1:parse_product",
        extract=_single(scraping_sandbox_json_v1.parse_product),
    ),
)

RUNTIME_REGISTRY: dict[tuple[str, str], ExtractorRuntime] = {
    (runtime.source, runtime.version): runtime for runtime in _RUNTIMES
}

if len(RUNTIME_REGISTRY) != len(_RUNTIMES):
    raise RuntimeError("duplicate extractor runtime key")


def resolve_extractor_runtime(*, source: str, version: str) -> ExtractorRuntime:
    try:
        return RUNTIME_REGISTRY[(source, version)]
    except KeyError as exc:
        raise ExtractorRuntimeNotFoundError(
            f"no extractor runtime registered for {source!r} version {version!r}"
        ) from exc


def list_extractor_runtimes() -> tuple[ExtractorRuntime, ...]:
    return tuple(sorted(_RUNTIMES, key=lambda item: (item.source, item.version)))
