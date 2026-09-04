from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from src.delivery.representations import product_representation, run_representation


def test_m17_product_representation_preserves_decimal_exactly():
    at = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    row = SimpleNamespace(
        source="demo",
        identity_key="record:42",
        source_record_id="42",
        canonical_product_url="https://example.test/p/42",
        title="Demo",
        price=Decimal("19.90"),
        compare_at_price=Decimal("25.00"),
        currency="USD",
        availability="IN_STOCK",
        quantity=3,
        category="demo",
        sku="SKU-42",
        categories=["demo"],
        variants=[{"name": "default", "price": "19.90"}],
        source_url="https://example.test/p/42?tracking=1",
        observed_at=at,
        updated_at=at,
        presence_status="ACTIVE",
        presence_observed_at=at,
    )
    result = product_representation(row)
    assert result["price"] == "19.90"
    assert result["compare_at_price"] == "25.00"
    assert result["identity_key"] == "record:42"
    assert "id" not in result
    assert "accepted_observation_id" not in result


def test_m17_run_representation_omits_stored_error_message():
    at = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    row = SimpleNamespace(
        id=7,
        source="demo",
        scope_key="default",
        trigger_type="SCHEDULED",
        started_at=at,
        finished_at=at,
        status="FAILED",
        retry_of_run_id=None,
        attempt=1,
        accounting_complete=False,
        records_seen=0,
        records_created=0,
        records_updated=0,
        records_no_change=0,
        records_stale=0,
        records_rejected=0,
        records_disappeared=0,
        records_reappeared=0,
        error_code="RUN_ABANDONED",
        error_message="internal detail that must not be delivered",
    )
    result = run_representation(row)
    assert result["error_code"] == "RUN_ABANDONED"
    assert "error_message" not in result
