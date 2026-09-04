from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from src.acquisition.models import RawEvidence
from src.main import main
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import Base, ProductHistoryRow, ProductRow
from src.storage.service import persist_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "book_product.html"
URL = "https://books.toscrape.com/catalogue/m13-cli/index.html"
T0 = datetime(2026, 9, 5, 21, 0, tzinfo=timezone.utc)


def _seed(database_url: str) -> None:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    evidence = RawEvidence.capture(
        evidence_id="m13-cli-evidence",
        source_url=URL,
        fetched_at=T0,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=FIXTURE.read_text(encoding="utf-8"),
    )
    persist_product_evidence(factory, evidence, changed_at=T0)
    engine.dispose()


def test_m13_cli_exports_and_restores_clean_database(tmp_path, capsys) -> None:
    source_url = f"sqlite+pysqlite:///{tmp_path / 'm13-source.db'}"
    target_url = f"sqlite+pysqlite:///{tmp_path / 'm13-target.db'}"
    bundle_path = tmp_path / "recovery.json"
    _seed(source_url)

    target_engine = create_database_engine(target_url)
    Base.metadata.create_all(target_engine)
    target_engine.dispose()

    assert main(["--database-url", source_url, "export-recovery", str(bundle_path)]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["status"] == "EXPORTED"
    assert exported["durable_rows"]["raw_evidence"] == 1
    assert exported["durable_rows"]["product_history"] == 1

    assert main(["--database-url", target_url, "restore-recovery", str(bundle_path)]) == 0
    restored = json.loads(capsys.readouterr().out)
    assert restored["status"] == "CONSISTENT"
    assert restored["stage"] == "RECOVERED_DATABASE"
    assert restored["products"] == 1
    assert restored["issues"] == []

    engine = create_database_engine(target_url)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            product = session.scalar(select(ProductRow))
            history = session.scalar(select(ProductHistoryRow))
            assert product is not None
            assert history is not None
            assert history.product_id == product.id
    finally:
        engine.dispose()


def test_m13_cli_rejects_tampered_bundle(tmp_path, capsys) -> None:
    source_url = f"sqlite+pysqlite:///{tmp_path / 'm13-tamper-source.db'}"
    target_url = f"sqlite+pysqlite:///{tmp_path / 'm13-tamper-target.db'}"
    bundle_path = tmp_path / "recovery-tampered.json"
    _seed(source_url)

    target_engine = create_database_engine(target_url)
    Base.metadata.create_all(target_engine)
    target_engine.dispose()

    assert main(["--database-url", source_url, "export-recovery", str(bundle_path)]) == 0
    capsys.readouterr()
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    payload["tables"]["raw_evidence"][0]["body"] += " "
    bundle_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["--database-url", target_url, "restore-recovery", str(bundle_path)])
    assert exc.value.code == 2
    assert "hash mismatch" in capsys.readouterr().err
