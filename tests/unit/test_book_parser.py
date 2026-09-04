from datetime import datetime, timezone
from pathlib import Path

from src.acquisition.models import RawEvidence
from src.books.parser import EXTRACTOR_VERSION, parse_book


FIXTURE = Path(__file__).parents[1] / "fixtures" / "book_product.html"
URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
T0 = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def test_raw_evidence_to_book_observation_preserves_traceability_and_source_values() -> None:
    body = FIXTURE.read_text(encoding="utf-8")
    evidence = RawEvidence.capture(
        evidence_id="evidence-001",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=body,
    )

    observation = parse_book(evidence)

    assert observation.evidence_id == evidence.id
    assert observation.extractor_version == EXTRACTOR_VERSION
    assert observation.source == "books_to_scrape"
    assert observation.source_url == URL
    assert observation.observed_at == T0
    assert observation.title_raw == "A Light in the Attic"
    assert observation.price_raw == "£51.77"
    assert observation.availability_raw == "In stock (22 available)"
    assert observation.category_raw == "Poetry"


def test_raw_evidence_hash_is_derived_from_exact_body() -> None:
    body = FIXTURE.read_text(encoding="utf-8")
    first = RawEvidence.capture(
        evidence_id="evidence-001",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html",
        body=body,
    )
    second = RawEvidence.capture(
        evidence_id="evidence-002",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html",
        body=body,
    )

    assert first.body == body
    assert first.body_hash == second.body_hash
