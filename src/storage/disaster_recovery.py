from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .models import (
    Base,
    CatalogRunChunkRow,
    CatalogRunRow,
    ProductHistoryRow,
    ProductObservationRow,
    ProductRow,
    RawEvidenceRow,
)
from .rebuild import rebuild_source_projection_in_place
from .reextraction import verify_source_reextraction
from .replay import _canonical_snapshot, replay_source_projection


RECOVERY_FORMAT_VERSION = 1


class RecoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecoveryIssue:
    code: str
    message: str
    source: str | None = None
    identity_key: str | None = None


@dataclass(frozen=True)
class RecoveryReport:
    status: str
    stage: str
    sources: tuple[str, ...]
    durable_rows: dict[str, int]
    products: int
    rolled_back: bool
    issues: tuple[RecoveryIssue, ...]

    @property
    def is_consistent(self) -> bool:
        return self.status == "CONSISTENT" and not self.issues


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _bundle_hash(payload_without_hash: dict[str, Any]) -> str:
    return sha256(_canonical_json(payload_without_hash).encode("utf-8")).hexdigest()


def _observation_payload(row: ProductObservationRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "evidence_id": row.evidence_id,
        "extractor_version": row.extractor_version,
        "source": row.source,
        "identity_key": row.identity_key,
        "source_record_id": row.source_record_id,
        "source_url": row.source_url,
        "observed_at": _iso(row.observed_at),
        "title_raw": row.title_raw,
        "price_raw": row.price_raw,
        "compare_at_price_raw": row.compare_at_price_raw,
        "currency_raw": row.currency_raw,
        "availability_raw": row.availability_raw,
        "category_raw": row.category_raw,
        "sku_raw": row.sku_raw,
        "categories_raw": list(row.categories_raw or []),
        "variants_raw": list(row.variants_raw or []),
        "canonical_product_url": row.canonical_product_url,
        "title": row.title,
        "price": str(row.price) if row.price is not None else None,
        "compare_at_price": str(row.compare_at_price) if row.compare_at_price is not None else None,
        "currency": row.currency,
        "availability": row.availability,
        "quantity": row.quantity,
        "category": row.category,
        "sku": row.sku,
        "categories": list(row.categories or []),
        "variants": list(row.variants or []),
        "state_decision": row.state_decision,
        "validation_errors": list(row.validation_errors or []),
    }


def export_recovery_bundle(session: Session) -> dict[str, Any]:
    """Export durable recovery state while deliberately excluding products.

    M13 treats ``products`` as a disposable projection. The recovery bundle
    preserves exact source evidence, persisted historical interpretation,
    catalog coverage proof, and the semantic ledger. RawEvidence is exported
    globally so parser-failure/orphan evidence is not silently lost merely
    because it has no downstream source row.
    """

    raw_evidence = [
        {
            "id": row.id,
            "source_url": row.source_url,
            "fetched_at": _iso(row.fetched_at),
            "status_code": row.status_code,
            "content_type": row.content_type,
            "body": row.body,
            "body_hash": row.body_hash,
        }
        for row in session.scalars(select(RawEvidenceRow).order_by(RawEvidenceRow.id))
    ]
    observations = [
        _observation_payload(row)
        for row in session.scalars(
            select(ProductObservationRow).order_by(ProductObservationRow.id)
        )
    ]
    catalog_runs = [
        {
            "id": row.id,
            "evidence_id": row.evidence_id,
            "run_key": row.run_key,
            "source": row.source,
            "scope_key": row.scope_key,
            "start_ref": row.start_ref,
            "observed_at": _iso(row.observed_at),
            "status": row.status,
            "record_count": row.record_count,
        }
        for row in session.scalars(select(CatalogRunRow).order_by(CatalogRunRow.id))
    ]
    catalog_run_chunks = [
        {
            "id": row.id,
            "catalog_run_id": row.catalog_run_id,
            "sequence": row.sequence,
            "requested_ref": row.requested_ref,
            "attempted_at": _iso(row.attempted_at),
            "evidence_id": row.evidence_id,
            "status": row.status,
            "next_ref": row.next_ref,
            "record_count": row.record_count,
            "error_code": row.error_code,
        }
        for row in session.scalars(
            select(CatalogRunChunkRow).order_by(CatalogRunChunkRow.id)
        )
    ]
    history = [
        {
            "id": row.id,
            "source": row.source,
            "identity_key": row.identity_key,
            # product_id is a projection link and is intentionally excluded.
            "observation_id": row.observation_id,
            "catalog_run_id": row.catalog_run_id,
            "decision": row.decision,
            "previous_state": row.previous_state,
            "new_state": row.new_state,
            "changed_at": _iso(row.changed_at),
        }
        for row in session.scalars(select(ProductHistoryRow).order_by(ProductHistoryRow.id))
    ]

    tables = {
        "raw_evidence": raw_evidence,
        "product_observations": observations,
        "catalog_runs": catalog_runs,
        "catalog_run_chunks": catalog_run_chunks,
        "product_history": history,
    }
    base = {"format_version": RECOVERY_FORMAT_VERSION, "tables": tables}
    return {**base, "bundle_hash": _bundle_hash(base)}


def write_recovery_bundle(session: Session, path: str | Path) -> dict[str, Any]:
    bundle = export_recovery_bundle(session)
    Path(path).write_text(
        json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return bundle


def load_recovery_bundle(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"cannot read recovery bundle: {exc}") from exc
    validate_recovery_bundle(payload)
    return payload


def validate_recovery_bundle(bundle: dict[str, Any]) -> None:
    if bundle.get("format_version") != RECOVERY_FORMAT_VERSION:
        raise RecoveryError(
            f"unsupported recovery format_version={bundle.get('format_version')!r}"
        )
    expected_hash = bundle.get("bundle_hash")
    if not isinstance(expected_hash, str):
        raise RecoveryError("recovery bundle is missing bundle_hash")
    base = {
        "format_version": bundle.get("format_version"),
        "tables": bundle.get("tables"),
    }
    if _bundle_hash(base) != expected_hash:
        raise RecoveryError("recovery bundle hash mismatch")
    tables = bundle.get("tables")
    required = {
        "raw_evidence",
        "product_observations",
        "catalog_runs",
        "catalog_run_chunks",
        "product_history",
    }
    if not isinstance(tables, dict) or set(tables) != required:
        raise RecoveryError("recovery bundle table set is invalid")
    if any(not isinstance(tables[name], list) for name in required):
        raise RecoveryError("recovery bundle tables must be arrays")


def recovery_bundle_counts(bundle: dict[str, Any]) -> dict[str, int]:
    tables = bundle["tables"]
    return {name: len(rows) for name, rows in sorted(tables.items())}


def recovery_bundle_sources(bundle: dict[str, Any]) -> tuple[str, ...]:
    tables = bundle["tables"]
    values = {
        row["source"]
        for table in ("product_observations", "catalog_runs", "product_history")
        for row in tables[table]
        if row.get("source")
    }
    return tuple(sorted(values))


def _database_is_empty(session: Session) -> bool:
    models = (
        RawEvidenceRow,
        ProductObservationRow,
        CatalogRunRow,
        CatalogRunChunkRow,
        ProductHistoryRow,
        ProductRow,
    )
    return all(session.scalar(select(func.count()).select_from(model)) == 0 for model in models)


def restore_recovery_bundle(session: Session, bundle: dict[str, Any]) -> None:
    """Restore durable rows into an already-migrated, empty database/schema.

    Exact primary keys are restored because ledger provenance references those
    identities. ``products`` is never restored from the bundle; it is rebuilt
    afterward from the recovered ledger.
    """

    validate_recovery_bundle(bundle)
    if not _database_is_empty(session):
        raise RecoveryError("restore target is not empty")
    tables = bundle["tables"]

    for item in tables["raw_evidence"]:
        session.add(
            RawEvidenceRow(
                id=item["id"],
                source_url=item["source_url"],
                fetched_at=_dt(item["fetched_at"]),
                status_code=item["status_code"],
                content_type=item["content_type"],
                body=item["body"],
                body_hash=item["body_hash"],
            )
        )
    session.flush()

    for item in tables["product_observations"]:
        session.add(
            ProductObservationRow(
                id=item["id"],
                evidence_id=item["evidence_id"],
                extractor_version=item["extractor_version"],
                source=item["source"],
                identity_key=item["identity_key"],
                source_record_id=item["source_record_id"],
                source_url=item["source_url"],
                observed_at=_dt(item["observed_at"]),
                title_raw=item["title_raw"],
                price_raw=item["price_raw"],
                compare_at_price_raw=item["compare_at_price_raw"],
                currency_raw=item["currency_raw"],
                availability_raw=item["availability_raw"],
                category_raw=item["category_raw"],
                sku_raw=item["sku_raw"],
                categories_raw=list(item["categories_raw"]),
                variants_raw=list(item["variants_raw"]),
                canonical_product_url=item["canonical_product_url"],
                title=item["title"],
                price=_decimal(item["price"]),
                compare_at_price=_decimal(item["compare_at_price"]),
                currency=item["currency"],
                availability=item["availability"],
                quantity=item["quantity"],
                category=item["category"],
                sku=item["sku"],
                categories=list(item["categories"]),
                variants=list(item["variants"]),
                state_decision=item["state_decision"],
                validation_errors=list(item["validation_errors"]),
            )
        )
    session.flush()

    for item in tables["catalog_runs"]:
        session.add(
            CatalogRunRow(
                id=item["id"],
                evidence_id=item["evidence_id"],
                run_key=item["run_key"],
                source=item["source"],
                scope_key=item["scope_key"],
                start_ref=item["start_ref"],
                observed_at=_dt(item["observed_at"]),
                status=item["status"],
                record_count=item["record_count"],
            )
        )
    session.flush()

    for item in tables["catalog_run_chunks"]:
        session.add(
            CatalogRunChunkRow(
                id=item["id"],
                catalog_run_id=item["catalog_run_id"],
                sequence=item["sequence"],
                requested_ref=item["requested_ref"],
                attempted_at=_dt(item["attempted_at"]),
                evidence_id=item["evidence_id"],
                status=item["status"],
                next_ref=item["next_ref"],
                record_count=item["record_count"],
                error_code=item["error_code"],
            )
        )
    session.flush()

    for item in tables["product_history"]:
        session.add(
            ProductHistoryRow(
                id=item["id"],
                source=item["source"],
                identity_key=item["identity_key"],
                product_id=None,
                observation_id=item["observation_id"],
                catalog_run_id=item["catalog_run_id"],
                decision=item["decision"],
                previous_state=item["previous_state"],
                new_state=item["new_state"],
                changed_at=_dt(item["changed_at"]),
            )
        )
    session.flush()


def _source_product_snapshots(session: Session) -> dict[tuple[str, str], dict[str, Any]]:
    snapshots: dict[tuple[str, str], dict[str, Any]] = {}
    rows = list(session.scalars(select(ProductRow).order_by(ProductRow.source, ProductRow.identity_key)))
    for row in rows:
        snapshots[(row.source, row.identity_key)] = _canonical_snapshot(
            {
                "source": row.source,
                "identity_key": row.identity_key,
                "source_record_id": row.source_record_id,
                "canonical_product_url": row.canonical_product_url,
                "title": row.title,
                "price": str(row.price),
                "compare_at_price": str(row.compare_at_price) if row.compare_at_price is not None else None,
                "currency": row.currency,
                "availability": row.availability,
                "quantity": row.quantity,
                "category": row.category,
                "sku": row.sku,
                "categories": list(row.categories or []),
                "variants": list(row.variants or []),
                "source_url": row.source_url,
                "observed_at": row.observed_at,
                "updated_at": row.updated_at,
                "presence_status": row.presence_status,
                "presence_observed_at": row.presence_observed_at,
            }
        )
    return snapshots



def _synchronize_autoincrement_sequences(session: Session) -> None:
    """Advance PostgreSQL sequences after restoring explicit primary keys.

    PostgreSQL does not move a SERIAL/IDENTITY sequence when rows are inserted
    with explicit ids. Without this step a successful disaster restore could
    fail on the very next write with a duplicate primary key. Other dialects
    either do not need this or manage rowid allocation differently.
    """

    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    for table_name in (
        "product_observations",
        "catalog_runs",
        "catalog_run_chunks",
        "product_history",
        "products",
    ):
        session.execute(
            text(
                f"SELECT setval("
                f"pg_get_serial_sequence('{table_name}', 'id'), "
                f"COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) "
                f"FROM {table_name}"
            )
        )


def recover_bundle_into_session(session: Session, bundle: dict[str, Any]) -> RecoveryReport:
    """Restore durable state, rebuild all product projections, then self-verify."""

    sources = recovery_bundle_sources(bundle)
    counts = recovery_bundle_counts(bundle)
    issues: list[RecoveryIssue] = []
    try:
        restore_recovery_bundle(session, bundle)
        _synchronize_autoincrement_sequences(session)
    except RecoveryError as exc:
        return RecoveryReport(
            status="DIVERGED",
            stage="RESTORE_DURABLE_STATE",
            sources=sources,
            durable_rows=counts,
            products=0,
            rolled_back=False,
            issues=(RecoveryIssue(code="RESTORE_FAILED", message=str(exc)),),
        )

    for source in sources:
        extraction = verify_source_reextraction(session, source=source)
        for item in extraction.issues:
            issues.append(
                RecoveryIssue(
                    code=f"EXTRACTION_{item.code}",
                    message=item.message,
                    source=source,
                    identity_key=item.identity_key,
                )
            )
        rebuilt = rebuild_source_projection_in_place(session, source=source)
        for item in rebuilt.issues:
            issues.append(
                RecoveryIssue(
                    code=f"REBUILD_{item.code}",
                    message=item.message,
                    source=source,
                    identity_key=item.identity_key,
                )
            )
        replay = replay_source_projection(session, source=source)
        for item in replay.issues:
            issues.append(
                RecoveryIssue(
                    code=f"REPLAY_{item.code}",
                    message=item.message,
                    source=source,
                    identity_key=item.identity_key,
                )
            )

    _synchronize_autoincrement_sequences(session)
    product_count = session.scalar(select(func.count()).select_from(ProductRow)) or 0
    return RecoveryReport(
        status="CONSISTENT" if not issues else "DIVERGED",
        stage="RECOVERED_DATABASE",
        sources=sources,
        durable_rows=counts,
        products=int(product_count),
        rolled_back=False,
        issues=tuple(issues),
    )


def verify_disaster_recovery(engine: Engine) -> RecoveryReport:
    """Prove recovery inside a genuinely empty PostgreSQL schema.

    The source database is read first. A fresh schema is then created in one
    transaction, current ORM tables are created there, only the durable bundle
    is restored, and ``products`` is rebuilt from the ledger. The recovered
    semantic projection is compared with the original projection. The outer
    transaction is rolled back, which removes the temporary schema and all
    recovered rows.
    """

    with Session(engine, expire_on_commit=False) as source_session:
        bundle = export_recovery_bundle(source_session)
        sources = recovery_bundle_sources(bundle)
        expected_products = _source_product_snapshots(source_session)
        pre_issues: list[RecoveryIssue] = []
        for source in sources:
            extraction = verify_source_reextraction(source_session, source=source)
            for item in extraction.issues:
                pre_issues.append(
                    RecoveryIssue(
                        code=f"PRE_EXTRACTION_{item.code}",
                        message=item.message,
                        source=source,
                        identity_key=item.identity_key,
                    )
                )
            replay = replay_source_projection(source_session, source=source)
            for item in replay.issues:
                pre_issues.append(
                    RecoveryIssue(
                        code=f"PRE_REPLAY_{item.code}",
                        message=item.message,
                        source=source,
                        identity_key=item.identity_key,
                    )
                )
        if pre_issues:
            return RecoveryReport(
                status="DIVERGED",
                stage="PRE_RECOVERY_CHECK",
                sources=sources,
                durable_rows=recovery_bundle_counts(bundle),
                products=len(expected_products),
                rolled_back=True,
                issues=tuple(pre_issues),
            )

    schema = f"m13_recovery_{uuid4().hex}"
    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        Base.metadata.create_all(bind=connection)

        with Session(bind=connection, expire_on_commit=False) as recovery_session:
            recovered = recover_bundle_into_session(recovery_session, bundle)
            issues = list(recovered.issues)
            actual_products = _source_product_snapshots(recovery_session)
            if actual_products != expected_products:
                expected_keys = set(expected_products)
                actual_keys = set(actual_products)
                for source, identity_key in sorted(expected_keys | actual_keys):
                    expected = expected_products.get((source, identity_key))
                    actual = actual_products.get((source, identity_key))
                    if expected != actual:
                        issues.append(
                            RecoveryIssue(
                                code="RECOVERED_PROJECTION_MISMATCH",
                                message="fresh-schema recovered projection differs from source",
                                source=source,
                                identity_key=identity_key,
                            )
                        )
            return RecoveryReport(
                status="CONSISTENT" if not issues else "DIVERGED",
                stage="CLEAN_SCHEMA_RECOVERY",
                sources=recovered.sources,
                durable_rows=recovered.durable_rows,
                products=len(actual_products),
                rolled_back=True,
                issues=tuple(issues),
            )
    finally:
        transaction.rollback()
        connection.close()
