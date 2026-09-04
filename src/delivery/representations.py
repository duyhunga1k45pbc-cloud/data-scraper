from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from src.storage.models import ProductHistoryRow, ProductRow, ScrapeRunRow


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def product_representation(row: ProductRow) -> dict[str, Any]:
    """Represent the trusted current projection without reinterpreting it."""

    return {
        "source": row.source,
        "identity_key": row.identity_key,
        "source_record_id": row.source_record_id,
        "canonical_product_url": row.canonical_product_url,
        "title": row.title,
        "price": _json_safe(row.price),
        "compare_at_price": _json_safe(row.compare_at_price),
        "currency": row.currency,
        "availability": row.availability,
        "quantity": row.quantity,
        "category": row.category,
        "sku": row.sku,
        "categories": _json_safe(row.categories or []),
        "variants": _json_safe(row.variants or []),
        "source_url": row.source_url,
        "observed_at": _json_safe(row.observed_at),
        "updated_at": _json_safe(row.updated_at),
        "presence_status": row.presence_status,
        "presence_observed_at": _json_safe(row.presence_observed_at),
    }


def history_representation(row: ProductHistoryRow) -> dict[str, Any]:
    """Represent one stable semantic-ledger entry."""

    return {
        "history_id": row.id,
        "source": row.source,
        "identity_key": row.identity_key,
        "decision": row.decision,
        "previous_state": _json_safe(row.previous_state),
        "new_state": _json_safe(row.new_state),
        "changed_at": _json_safe(row.changed_at),
        "observation_id": row.observation_id,
        "catalog_run_id": row.catalog_run_id,
    }


def run_representation(row: ScrapeRunRow) -> dict[str, Any]:
    """Represent operational execution state; never merge it into product truth."""

    return {
        "run_id": row.id,
        "source": row.source,
        "scope_key": row.scope_key,
        "trigger_type": row.trigger_type,
        "started_at": _json_safe(row.started_at),
        "finished_at": _json_safe(row.finished_at),
        "status": row.status,
        "retry_of_run_id": row.retry_of_run_id,
        "attempt": row.attempt,
        "accounting_complete": row.accounting_complete,
        "records_seen": row.records_seen,
        "records_created": row.records_created,
        "records_updated": row.records_updated,
        "records_no_change": row.records_no_change,
        "records_stale": row.records_stale,
        "records_rejected": row.records_rejected,
        "records_disappeared": row.records_disappeared,
        "records_reappeared": row.records_reappeared,
        "error_code": row.error_code,
    }
