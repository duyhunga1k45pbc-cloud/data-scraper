from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.acquisition.models import RawEvidence
from src.main import main
from src.scrapify_js.parser import parse_catalog
from src.storage.models import Base
from src.storage.service import persist_product_observations


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scrapify_products.json"
URL = "https://scrapifydatalabs.com/data/products.json"
T0 = datetime(2026, 9, 5, 1, 0, tzinfo=timezone.utc)


def _seed(database_url: str) -> None:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    evidence = RawEvidence.capture(
        evidence_id="cli-m2-evidence",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="application/json",
        body=FIXTURE.read_text(encoding="utf-8"),
    )
    persist_product_observations(factory, evidence, parse_catalog(evidence), changed_at=T0)
    engine.dispose()


def test_cli_show_record_delivers_source_id_product(tmp_path, capsys) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli-m2.db'}"
    _seed(database_url)

    assert (
        main(
            [
                "--database-url",
                database_url,
                "show-record",
                "scrapify_js",
                "p-1001",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["identity"]["source_record_id"] == "p-1001"
    assert payload["identity"]["canonical_product_url"] is None
    assert payload["price"] == "129.99"
    assert payload["currency"] == "USD"


def test_cli_history_record_delivers_accepted_transition(tmp_path, capsys) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli-m2.db'}"
    _seed(database_url)

    assert (
        main(
            [
                "--database-url",
                database_url,
                "history-record",
                "scrapify_js",
                "p-1001",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["decision"] == "CREATE"
    assert payload[0]["new_state"]["source_record_id"] == "p-1001"
