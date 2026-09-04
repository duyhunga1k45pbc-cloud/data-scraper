from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.delivery.api import create_app
from src.storage.models import Base, ProductHistoryRow, ProductRow, ScrapeRunRow


def _seed(factory):
    at = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    with factory() as session:
        with session.begin():
            product = ProductRow(
                source="m17-source",
                identity_key="record:42",
                source_record_id="42",
                canonical_product_url="https://example.test/products/42",
                title="Delivery Product",
                price=Decimal("19.90"),
                compare_at_price=Decimal("25.00"),
                currency="USD",
                availability="IN_STOCK",
                quantity=5,
                category="demo",
                sku="SKU-42",
                categories=["demo"],
                variants=[],
                source_url="https://example.test/products/42",
                observed_at=at,
                updated_at=at,
                presence_status="ACTIVE",
                presence_observed_at=at,
                accepted_observation_id=1,
            )
            session.add(product)
            session.flush()
            session.add(
                ProductHistoryRow(
                    source="m17-source",
                    identity_key="record:42",
                    product_id=product.id,
                    observation_id=1,
                    catalog_run_id=None,
                    decision="CREATE",
                    previous_state=None,
                    new_state={"title": "Delivery Product", "price": "19.90"},
                    changed_at=at,
                )
            )
            session.add(
                ScrapeRunRow(
                    source="m17-source",
                    scope_key="default",
                    trigger_type="MANUAL",
                    started_at=at,
                    finished_at=at,
                    status="SUCCEEDED",
                    retry_of_run_id=None,
                    attempt=1,
                    accounting_complete=True,
                    records_seen=1,
                    records_created=1,
                    records_updated=0,
                    records_no_change=0,
                    records_stale=0,
                    records_rejected=0,
                    records_disappeared=0,
                    records_reappeared=0,
                    error_code=None,
                    error_message=None,
                )
            )


def _counts(factory):
    with factory() as session:
        return (
            session.scalar(select(func.count()).select_from(ProductRow)),
            session.scalar(select(func.count()).select_from(ProductHistoryRow)),
            session.scalar(select(func.count()).select_from(ScrapeRunRow)),
        )


def test_m17_api_delivers_projection_history_and_runs_without_mutation(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'm17.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    _seed(factory)
    before = _counts(factory)

    with TestClient(create_app(session_factory=factory)) as client:
        response = client.get("/products", params={"source": "m17-source"})
        assert response.status_code == 200
        products = response.json()
        assert products["returned"] == 1
        assert products["items"][0]["identity_key"] == "record:42"
        assert products["items"][0]["price"] == "19.90"

        response = client.get(
            "/product",
            params={"source": "m17-source", "identity_key": "record:42"},
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Delivery Product"

        response = client.get(
            "/product/history",
            params={"source": "m17-source", "identity_key": "record:42"},
        )
        assert response.status_code == 200
        assert response.json()["items"][0]["decision"] == "CREATE"

        response = client.get("/runs", params={"source": "m17-source"})
        assert response.status_code == 200
        assert response.json()["items"][0]["status"] == "SUCCEEDED"
        assert "error_message" not in response.json()["items"][0]

        missing = client.get(
            "/product",
            params={"source": "m17-source", "identity_key": "missing"},
        )
        assert missing.status_code == 404

    assert _counts(factory) == before
    engine.dispose()
