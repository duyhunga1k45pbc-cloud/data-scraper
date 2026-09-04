from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select

from src.acquisition.models import RawEvidence
from src.main import main
from src.storage.database import create_session_factory
from src.storage.models import Base, ProductRow
from src.storage.service import persist_product_evidence


URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
T0 = datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parents[1] / "fixtures" / "book_product.html"


def _seed(database_url: str) -> None:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    evidence = RawEvidence.capture(
        evidence_id="m10-cli-evidence",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html",
        body=FIXTURE.read_text(),
    )
    persist_product_evidence(factory, evidence, changed_at=T0)
    engine.dispose()


def test_m10_cli_verify_replay_reports_consistent_projection(tmp_path, capsys) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'm10-cli.db'}"
    _seed(database_url)

    assert main(["--database-url", database_url, "verify-replay", "books_to_scrape"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "CONSISTENT"
    assert payload["products"] == 1
    assert payload["issues"] == []


def test_m10_cli_verify_replay_returns_nonzero_on_projection_drift(tmp_path, capsys) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'm10-cli-drift.db'}"
    _seed(database_url)

    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        with session.begin():
            row = session.scalar(select(ProductRow).where(ProductRow.source == "books_to_scrape"))
            assert row is not None
            row.price = Decimal("999.00")
    engine.dispose()

    assert main(["--database-url", database_url, "verify-replay", "books_to_scrape"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "DIVERGED"
    assert "CURRENT_PROJECTION_MISMATCH" in {item["code"] for item in payload["issues"]}
