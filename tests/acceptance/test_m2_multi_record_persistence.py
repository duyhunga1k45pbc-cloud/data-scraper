from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.acquisition.models import RawEvidence
from src.products.models import StateDecision
from src.scrapify_js.parser import parse_catalog
from src.storage.models import (
    Base,
    ProductHistoryRow,
    ProductObservationRow,
    ProductRow,
    RawEvidenceRow,
)
from src.storage.service import persist_product_observations


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scrapify_products.json"
URL = "https://scrapifydatalabs.com/data/products.json"
T0 = datetime(2026, 9, 5, 1, 0, tzinfo=timezone.utc)


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _evidence() -> RawEvidence:
    return RawEvidence.capture(
        evidence_id="m2-scrapify-batch",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="application/json",
        body=FIXTURE.read_text(encoding="utf-8"),
    )


def test_m2_one_evidence_persists_multiple_independent_product_states() -> None:
    session_factory = _factory()
    evidence = _evidence()

    results = persist_product_observations(
        session_factory,
        evidence,
        parse_catalog(evidence),
        changed_at=T0,
    )

    assert len(results) == 3
    assert {run.transition.decision for run in results} == {StateDecision.CREATE}

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(RawEvidenceRow)) == 1
        assert session.scalar(select(func.count()).select_from(ProductObservationRow)) == 3
        assert session.scalar(select(func.count()).select_from(ProductRow)) == 3
        assert session.scalar(select(func.count()).select_from(ProductHistoryRow)) == 3

        rows = list(session.scalars(select(ProductRow).order_by(ProductRow.source_record_id)))
        assert [row.source_record_id for row in rows] == ["p-1001", "p-1002", "p-1003"]
        assert [row.identity_key for row in rows] == ["id:p-1001", "id:p-1002", "id:p-1003"]
        assert all(row.canonical_product_url is None for row in rows)


def test_m2_reprocessing_same_batch_creates_no_duplicate_effects() -> None:
    session_factory = _factory()
    evidence = _evidence()
    observations = parse_catalog(evidence)

    first = persist_product_observations(
        session_factory,
        evidence,
        observations,
        changed_at=T0,
    )
    second = persist_product_observations(
        session_factory,
        evidence,
        observations,
        changed_at=T0,
    )

    assert {run.transition.decision for run in first} == {StateDecision.CREATE}
    assert {run.transition.decision for run in second} == {StateDecision.NO_CHANGE}

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(RawEvidenceRow)) == 1
        assert session.scalar(select(func.count()).select_from(ProductObservationRow)) == 3
        assert session.scalar(select(func.count()).select_from(ProductRow)) == 3
        assert session.scalar(select(func.count()).select_from(ProductHistoryRow)) == 3
