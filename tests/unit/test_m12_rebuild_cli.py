from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from src.acquisition.models import RawEvidence
from src.main import main
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import Base, ProductHistoryRow, ProductRow
from src.storage.service import persist_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "book_product.html"
URL = "https://books.toscrape.com/catalogue/m12-cli/index.html"
T0 = datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc)


def _seed(database_url: str) -> tuple[int, int]:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    evidence = RawEvidence.capture(
        evidence_id="m12-cli-evidence",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=FIXTURE.read_text(encoding="utf-8"),
    )
    persist_product_evidence(factory, evidence, changed_at=T0)
    with factory() as session:
        product = session.scalar(
            select(ProductRow).where(ProductRow.source == "books_to_scrape")
        )
        history = session.scalar(
            select(ProductHistoryRow).where(ProductHistoryRow.source == "books_to_scrape")
        )
        assert product is not None
        assert history is not None
        result = (product.id, history.product_id)
    engine.dispose()
    assert result[1] is not None
    return result[0], int(result[1])


def test_m12_verify_rebuild_cli_runs_real_rebuild_then_rolls_back(tmp_path, capsys) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'm12-cli.db'}"
    product_id, history_product_id = _seed(database_url)

    code = main(
        [
            "--database-url",
            database_url,
            "verify-rebuild",
            "books_to_scrape",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "CONSISTENT"
    assert payload["stage"] == "REBUILT_PROJECTION"
    assert payload["products"] == 1
    assert payload["history_rows"] == 1
    assert payload["rolled_back"] is True
    assert payload["issues"] == []

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            product = session.scalar(
                select(ProductRow).where(ProductRow.source == "books_to_scrape")
            )
            history = session.scalar(
                select(ProductHistoryRow).where(ProductHistoryRow.source == "books_to_scrape")
            )
            assert product is not None
            assert history is not None
            assert product.id == product_id
            assert history.product_id == history_product_id
    finally:
        engine.dispose()


def test_m12_verify_rebuild_cli_refuses_diverged_current_projection(tmp_path, capsys) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'm12-cli-drift.db'}"
    product_id, _ = _seed(database_url)

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            with session.begin():
                product = session.get(ProductRow, product_id)
                assert product is not None
                product.price = Decimal("999.00")
    finally:
        engine.dispose()

    code = main(
        [
            "--database-url",
            database_url,
            "verify-rebuild",
            "books_to_scrape",
        ]
    )
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "DIVERGED"
    assert payload["stage"] == "PRE_REBUILD_CHECK"
    assert payload["rolled_back"] is True
    assert "CURRENT_PROJECTION_MISMATCH" in {
        item["code"] for item in payload["issues"]
    }
