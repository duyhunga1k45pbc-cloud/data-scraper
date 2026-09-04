from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from src.acquisition.models import RawEvidence
from src.scrapify_js.parser import parse_catalog
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import Base, ProductObservationRow
from src.storage.reextraction import verify_source_reextraction
from src.storage.service import persist_product_evidence, persist_product_observations


BOOK_FIXTURE = Path(__file__).parents[1] / "fixtures" / "book_product.html"
SCRAPIFY_FIXTURE = Path(__file__).parents[1] / "fixtures" / "scrapify_products.json"
BOOK_URL = "https://books.toscrape.com/catalogue/m11-book/index.html"
SCRAPIFY_URL = "https://scrapifydatalabs.com/data/products.json"
T0 = datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc)


def _factory(tmp_path, name: str):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")
    Base.metadata.create_all(engine)
    return engine, create_session_factory(engine)


def _book_evidence() -> RawEvidence:
    return RawEvidence.capture(
        evidence_id="m11-book-evidence",
        source_url=BOOK_URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=BOOK_FIXTURE.read_text(encoding="utf-8"),
    )


def _scrapify_evidence() -> RawEvidence:
    return RawEvidence.capture(
        evidence_id="m11-scrapify-evidence",
        source_url=SCRAPIFY_URL,
        fetched_at=T0,
        status_code=200,
        content_type="application/json",
        body=SCRAPIFY_FIXTURE.read_text(encoding="utf-8"),
    )


def test_m11_reextracts_single_record_evidence_with_recorded_version(tmp_path) -> None:
    engine, factory = _factory(tmp_path, "m11-book.db")
    try:
        persist_product_evidence(factory, _book_evidence(), changed_at=T0)
        with factory() as session:
            report = verify_source_reextraction(session, source="books_to_scrape")

        assert report.is_consistent
        assert report.issues == ()
        assert report.observations == 1
        assert len(report.evidence) == 1
        assert report.evidence[0].extractor_version == "books-to-scrape-v1"
        assert report.evidence[0].persisted_observations == 1
        assert report.evidence[0].reextracted_observations == 1
    finally:
        engine.dispose()


def test_m11_reextracts_one_to_many_evidence_as_observation_multiset(tmp_path) -> None:
    engine, factory = _factory(tmp_path, "m11-scrapify.db")
    try:
        evidence = _scrapify_evidence()
        persist_product_observations(
            factory,
            evidence,
            parse_catalog(evidence),
            changed_at=T0,
        )
        with factory() as session:
            report = verify_source_reextraction(session, source="scrapify_js")

        assert report.is_consistent
        assert report.observations == 3
        assert len(report.evidence) == 1
        assert report.evidence[0].persisted_observations == 3
        assert report.evidence[0].reextracted_observations == 3
    finally:
        engine.dispose()


def test_m11_detects_persisted_extraction_drift(tmp_path) -> None:
    engine, factory = _factory(tmp_path, "m11-drift.db")
    try:
        persist_product_evidence(factory, _book_evidence(), changed_at=T0)
        with factory() as session:
            with session.begin():
                row = session.scalar(select(ProductObservationRow))
                assert row is not None
                row.title_raw = "tampered title"

        with factory() as session:
            report = verify_source_reextraction(session, source="books_to_scrape")

        assert not report.is_consistent
        codes = {item.code for item in report.issues}
        assert "PERSISTED_OBSERVATION_NOT_REPRODUCED" in codes
        assert "UNPERSISTED_REEXTRACTED_OBSERVATION" in codes
    finally:
        engine.dispose()



def test_m11_detects_raw_evidence_hash_drift_before_trusting_reextraction(tmp_path) -> None:
    from src.storage.models import RawEvidenceRow

    engine, factory = _factory(tmp_path, "m11-raw-drift.db")
    try:
        persist_product_evidence(factory, _book_evidence(), changed_at=T0)
        with factory() as session:
            with session.begin():
                row = session.get(RawEvidenceRow, "m11-book-evidence")
                assert row is not None
                row.body = row.body.replace("A Light in the Attic", "Changed upstream body")

        with factory() as session:
            report = verify_source_reextraction(session, source="books_to_scrape")

        assert not report.is_consistent
        assert "RAW_EVIDENCE_HASH_MISMATCH" in {item.code for item in report.issues}
    finally:
        engine.dispose()

def test_m11_refuses_unregistered_persisted_extractor_version(tmp_path) -> None:
    engine, factory = _factory(tmp_path, "m11-version.db")
    try:
        persist_product_evidence(factory, _book_evidence(), changed_at=T0)
        with factory() as session:
            with session.begin():
                row = session.scalar(select(ProductObservationRow))
                assert row is not None
                row.extractor_version = "books-to-scrape-v999"

        with factory() as session:
            report = verify_source_reextraction(session, source="books_to_scrape")

        assert not report.is_consistent
        assert [item.code for item in report.issues] == ["EXTRACTOR_RUNTIME_NOT_FOUND"]
    finally:
        engine.dispose()
