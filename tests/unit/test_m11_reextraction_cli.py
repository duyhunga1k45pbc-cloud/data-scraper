from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.acquisition.models import RawEvidence
from src.main import main
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import Base
from src.storage.service import persist_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "book_product.html"
URL = "https://books.toscrape.com/catalogue/m11-cli/index.html"
T0 = datetime(2026, 9, 5, 9, 30, tzinfo=timezone.utc)


def _seed(database_url: str) -> None:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    evidence = RawEvidence.capture(
        evidence_id="m11-cli-evidence",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html",
        body=FIXTURE.read_text(encoding="utf-8"),
    )
    persist_product_evidence(factory, evidence, changed_at=T0)
    engine.dispose()


def test_m11_cli_verify_extraction_reports_versioned_raw_replay(tmp_path, capsys) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'm11-cli.db'}"
    _seed(database_url)

    assert main(["--database-url", database_url, "verify-extraction", "books_to_scrape"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "evidence_groups": 1,
        "issues": [],
        "observations": 1,
        "source": "books_to_scrape",
        "status": "CONSISTENT",
    }
