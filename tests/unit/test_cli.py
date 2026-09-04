from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.books.models import Availability, Currency
from src.main import main
from src.storage.models import Base, BookHistoryRow, BookObservationRow, BookRow, RawEvidenceRow


URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
T0 = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _seed_database(database_url: str) -> None:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with factory() as session:
        with session.begin():
            evidence = RawEvidenceRow(
                id="cli-evidence",
                source_url=URL,
                fetched_at=T0,
                status_code=200,
                content_type="text/html",
                body="<html></html>",
                body_hash="a" * 64,
            )
            session.add(evidence)
            session.flush()

            observation = BookObservationRow(
                evidence_id=evidence.id,
                extractor_version="books-to-scrape-v1",
                source="books_to_scrape",
                identity_key=f"url:{URL}",
                source_url=URL,
                observed_at=T0,
                title_raw="A Light in the Attic",
                price_raw="£51.77",
                availability_raw="In stock (22 available)",
                category_raw="Poetry",
                canonical_product_url=URL,
                title="A Light in the Attic",
                price=Decimal("51.77"),
                currency=Currency.GBP.value,
                availability=Availability.IN_STOCK.value,
                quantity=22,
                category="Poetry",
                state_decision="CREATE",
                validation_errors=[],
            )
            session.add(observation)
            session.flush()

            book = BookRow(
                source="books_to_scrape",
                identity_key=f"url:{URL}",
                canonical_product_url=URL,
                title="A Light in the Attic",
                price=Decimal("51.77"),
                currency=Currency.GBP.value,
                availability=Availability.IN_STOCK.value,
                quantity=22,
                category="Poetry",
                source_url=URL,
                observed_at=T0,
                updated_at=T0,
                presence_status="ACTIVE",
                presence_observed_at=T0,
                accepted_observation_id=observation.id,
            )
            session.add(book)
            session.flush()

            session.add(
                BookHistoryRow(
                    source="books_to_scrape",
                    identity_key=f"url:{URL}",
                    book_id=book.id,
                    observation_id=observation.id,
                    decision="CREATE",
                    previous_state=None,
                    new_state={
                        "source": "books_to_scrape",
                        "canonical_product_url": URL,
                        "title": "A Light in the Attic",
                        "price": "51.77",
                        "currency": "GBP",
                        "availability": "IN_STOCK",
                        "quantity": 22,
                        "category": "Poetry",
                        "source_url": URL,
                        "observed_at": T0.isoformat(),
                        "updated_at": T0.isoformat(),
                    },
                    changed_at=T0,
                )
            )

    engine.dispose()


def test_cli_show_delivers_current_trusted_state(tmp_path, capsys) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli.db'}"
    _seed_database(database_url)

    assert main(["--database-url", database_url, "show", URL]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["identity"]["canonical_product_url"] == URL
    assert payload["title"] == "A Light in the Attic"
    assert payload["price"] == "51.77"
    assert payload["availability"] == "IN_STOCK"


def test_cli_history_delivers_accepted_transitions(tmp_path, capsys) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli.db'}"
    _seed_database(database_url)

    assert main(["--database-url", database_url, "history", URL]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["decision"] == "CREATE"
    assert payload[0]["previous_state"] is None
    assert payload[0]["new_state"]["price"] == "51.77"
