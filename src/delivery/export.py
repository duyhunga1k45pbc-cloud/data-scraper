from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.storage.models import ProductRow

from .representations import product_representation

ExportFormat = Literal["json", "csv"]


@dataclass(frozen=True)
class ExportResult:
    output_path: Path
    format: ExportFormat
    records: int
    source: str | None


_CSV_FIELDS = (
    "source",
    "identity_key",
    "source_record_id",
    "canonical_product_url",
    "title",
    "price",
    "compare_at_price",
    "currency",
    "availability",
    "quantity",
    "category",
    "sku",
    "categories",
    "variants",
    "source_url",
    "observed_at",
    "updated_at",
    "presence_status",
    "presence_observed_at",
)


def _load_products(
    session_factory: sessionmaker[Session],
    *,
    source: str | None,
) -> tuple[dict, ...]:
    stmt = select(ProductRow).order_by(ProductRow.source, ProductRow.identity_key)
    if source is not None:
        stmt = stmt.where(ProductRow.source == source)
    with session_factory() as session:
        rows = tuple(session.scalars(stmt))
    return tuple(product_representation(row) for row in rows)


def _csv_value(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if value is None:
        return ""
    return value


def export_current_products(
    session_factory: sessionmaker[Session],
    *,
    output_path: str | Path,
    format: ExportFormat,
    source: str | None = None,
) -> ExportResult:
    """Export the current trusted projection without changing it."""

    if format not in {"json", "csv"}:
        raise ValueError("format must be 'json' or 'csv'")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = _load_products(session_factory, source=source)

    if format == "json":
        path.write_text(
            json.dumps(records, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    else:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            for record in records:
                writer.writerow({key: _csv_value(record.get(key)) for key in _CSV_FIELDS})

    return ExportResult(
        output_path=path,
        format=format,
        records=len(records),
        source=source,
    )
