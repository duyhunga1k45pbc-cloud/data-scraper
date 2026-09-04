from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.acquisition.models import RawEvidence
from src.main import main
from src.storage.models import Base
from src.storage.service import persist_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scraping_sandbox_product.html"
URL = "https://scrapingsandbox.com/product/1"
T0 = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)


def _seed(database_url: str) -> None:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    evidence = RawEvidence.capture(
        evidence_id="cli-m3-evidence",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html",
        body=FIXTURE.read_text(encoding="utf-8"),
    )
    persist_product_evidence(factory, evidence, changed_at=T0)
    engine.dispose()


def test_cli_show_url_finds_product_whose_primary_identity_is_source_record_id(
    tmp_path, capsys
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli-m3.db'}"
    _seed(database_url)

    assert main(["--database-url", database_url, "show", URL]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["identity"]["source_record_id"] == "1"
    assert payload["identity"]["canonical_product_url"] == URL
    assert payload["sku"] == "SKU-HEA-0001"
    assert len(payload["variants"]) == 4


def test_cli_history_url_finds_product_whose_primary_identity_is_source_record_id(
    tmp_path, capsys
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli-m3.db'}"
    _seed(database_url)

    assert main(["--database-url", database_url, "history", URL]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["decision"] == "CREATE"
    assert payload[0]["new_state"]["source_record_id"] == "1"
    assert payload[0]["new_state"]["canonical_product_url"] == URL
