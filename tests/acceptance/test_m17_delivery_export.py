import csv
import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.delivery.export import export_current_products
from src.storage.models import Base, ProductRow


def test_m17_json_and_csv_export_use_same_trusted_projection(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'export.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    at = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    with factory() as session:
        with session.begin():
            session.add(
                ProductRow(
                    source="m17-export",
                    identity_key="record:9",
                    source_record_id="9",
                    canonical_product_url="https://example.test/9",
                    title="Export Product",
                    price=Decimal("7.50"),
                    compare_at_price=None,
                    currency="USD",
                    availability="IN_STOCK",
                    quantity=None,
                    category=None,
                    sku=None,
                    categories=["one", "two"],
                    variants=[],
                    source_url="https://example.test/9",
                    observed_at=at,
                    updated_at=at,
                    presence_status="ACTIVE",
                    presence_observed_at=at,
                    accepted_observation_id=1,
                )
            )

    json_path = tmp_path / "products.json"
    csv_path = tmp_path / "products.csv"
    json_result = export_current_products(
        factory, output_path=json_path, format="json", source="m17-export"
    )
    csv_result = export_current_products(
        factory, output_path=csv_path, format="csv", source="m17-export"
    )
    assert json_result.records == csv_result.records == 1

    json_rows = json.loads(json_path.read_text(encoding="utf-8"))
    with csv_path.open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert json_rows[0]["identity_key"] == csv_rows[0]["identity_key"] == "record:9"
    assert json_rows[0]["price"] == csv_rows[0]["price"] == "7.50"
    engine.dispose()
