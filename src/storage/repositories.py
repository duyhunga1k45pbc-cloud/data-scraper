from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from typing import Iterable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.acquisition.models import RawEvidence
from src.products.models import (
    Availability,
    Currency,
    CurrentProductState,
    CurrentProductVariantState,
    ProductHistoryEntry,
    ProductIdentity,
    ProductPresenceStatus,
    ProductNormalizedData,
    ProductObservation,
    ProductVariantNormalizedData,
    ProductVariantObservation,
    StateDecision,
    StateTransitionResult,
)

from .models import (
    CatalogRunChunkRow,
    CatalogRunRow,
    ProductHistoryRow,
    ProductObservationRow,
    ProductRow,
    RawEvidenceRow,
)


class PersistenceConflictError(RuntimeError):
    pass


def _same_datetime(left: datetime, right: datetime) -> bool:
    def as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    return as_utc(left) == as_utc(right)


def _identity_key(
    *,
    canonical_product_url: str | None,
    source_record_id: str | None,
) -> str | None:
    if source_record_id:
        return f"id:{source_record_id}"
    if canonical_product_url:
        return f"url:{canonical_product_url}"
    return None


def _raw_variant_payload(variant: ProductVariantObservation) -> dict[str, object]:
    return {
        "sku_raw": variant.sku_raw,
        "price_raw": variant.price_raw,
        "availability_raw": variant.availability_raw,
        "options_raw": [list(pair) for pair in variant.options_raw],
    }


def _normalized_variant_payload(variant: ProductVariantNormalizedData) -> dict[str, object]:
    return {
        "key": variant.key,
        "sku": variant.sku,
        "options": [list(pair) for pair in variant.options],
        "price": str(variant.price) if variant.price is not None else None,
        "availability": (
            variant.availability.value if variant.availability is not None else None
        ),
    }


def _state_variant_payload(variant: CurrentProductVariantState) -> dict[str, object]:
    return {
        "key": variant.key,
        "sku": variant.sku,
        "options": [list(pair) for pair in variant.options],
        "price": str(variant.price),
        "availability": variant.availability.value,
    }


def _variant_state_from_payload(payload: dict) -> CurrentProductVariantState:
    options_raw = payload.get("options") or []
    options = tuple((str(item[0]), str(item[1])) for item in options_raw)
    return CurrentProductVariantState(
        key=str(payload["key"]),
        sku=str(payload["sku"]) if payload.get("sku") is not None else None,
        options=options,
        price=Decimal(str(payload["price"])),
        availability=Availability(str(payload["availability"])),
    )


def _product_identity_advisory_lock_id(source: str, identity_key: str) -> int:
    """Return a stable signed 64-bit PostgreSQL advisory-lock key.

    Hash collisions only over-serialize unrelated identities; they cannot allow
    two workers for the same identity to proceed concurrently.
    """

    token = f"{source}\x1f{identity_key}".encode("utf-8")
    return int.from_bytes(sha256(token).digest()[:8], byteorder="big", signed=True)




def lock_catalog_scope_for_reconciliation(
    session: Session,
    *,
    source: str,
    scope_key: str,
) -> None:
    """Serialize catalog reconciliation for one source scope on PostgreSQL."""

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    lock_id = _product_identity_advisory_lock_id(
        f"catalog:{source}",
        f"scope:{scope_key}",
    )
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": lock_id},
    )

def lock_product_identity_keys_for_transition(
    session: Session,
    identities: Iterable[tuple[str, str]],
) -> None:
    """Acquire stable PostgreSQL advisory locks for explicit product identities."""

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return

    lock_ids = {
        _product_identity_advisory_lock_id(source, identity_key)
        for source, identity_key in identities
    }
    for lock_id in sorted(lock_ids):
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": lock_id},
        )


def lock_product_identities_for_transition(
    session: Session,
    products: Iterable[ProductNormalizedData],
) -> None:
    """Serialize transition decisions per product identity on PostgreSQL."""

    identities: list[tuple[str, str]] = []
    for product in products:
        key = _identity_key(
            canonical_product_url=product.canonical_product_url,
            source_record_id=product.source_record_id,
        )
        if key is not None:
            identities.append((product.source, key))
    lock_product_identity_keys_for_transition(session, identities)

def persist_raw_evidence(session: Session, evidence: RawEvidence) -> RawEvidenceRow:
    existing = session.get(RawEvidenceRow, evidence.id)
    if existing is not None:
        same_evidence = (
            existing.source_url == evidence.source_url
            and _same_datetime(existing.fetched_at, evidence.fetched_at)
            and existing.status_code == evidence.status_code
            and existing.content_type == evidence.content_type
            and existing.body == evidence.body
            and existing.body_hash == evidence.body_hash
        )
        if not same_evidence:
            raise PersistenceConflictError(
                f"raw evidence id {evidence.id!r} already exists with different content"
            )
        return existing

    row = RawEvidenceRow(
        id=evidence.id,
        source_url=evidence.source_url,
        fetched_at=evidence.fetched_at,
        status_code=evidence.status_code,
        content_type=evidence.content_type,
        body=evidence.body,
        body_hash=evidence.body_hash,
    )
    session.add(row)
    session.flush()
    return row


def persist_catalog_run(
    session: Session,
    *,
    run_key: str,
    evidence_id: str | None,
    source: str,
    scope_key: str,
    start_ref: str,
    observed_at: datetime,
    status: str,
    record_count: int,
) -> CatalogRunRow:
    existing = session.scalar(
        select(CatalogRunRow).where(CatalogRunRow.run_key == run_key)
    )
    if existing is not None:
        same_run = (
            existing.evidence_id == evidence_id
            and existing.source == source
            and existing.scope_key == scope_key
            and existing.start_ref == start_ref
            and existing.status == status
            and existing.record_count == record_count
            and _same_datetime(existing.observed_at, observed_at)
        )
        if not same_run:
            raise PersistenceConflictError(
                "catalog run key already exists with different coverage metadata"
            )
        return existing

    row = CatalogRunRow(
        run_key=run_key,
        evidence_id=evidence_id,
        source=source,
        scope_key=scope_key,
        start_ref=start_ref,
        observed_at=observed_at,
        status=status,
        record_count=record_count,
    )
    session.add(row)
    session.flush()
    return row


def persist_catalog_run_chunk(
    session: Session,
    *,
    catalog_run_id: int,
    sequence: int,
    requested_ref: str,
    attempted_at: datetime,
    evidence_id: str | None,
    status: str,
    next_ref: str | None,
    record_count: int,
    error_code: str | None,
) -> CatalogRunChunkRow:
    existing = session.scalar(
        select(CatalogRunChunkRow).where(
            CatalogRunChunkRow.catalog_run_id == catalog_run_id,
            CatalogRunChunkRow.sequence == sequence,
        )
    )
    if existing is not None:
        same_chunk = (
            existing.requested_ref == requested_ref
            and _same_datetime(existing.attempted_at, attempted_at)
            and existing.evidence_id == evidence_id
            and existing.status == status
            and existing.next_ref == next_ref
            and existing.record_count == record_count
            and existing.error_code == error_code
        )
        if not same_chunk:
            raise PersistenceConflictError(
                "catalog run chunk already exists with different evidence metadata"
            )
        return existing

    row = CatalogRunChunkRow(
        catalog_run_id=catalog_run_id,
        sequence=sequence,
        requested_ref=requested_ref,
        attempted_at=attempted_at,
        evidence_id=evidence_id,
        status=status,
        next_ref=next_ref,
        record_count=record_count,
        error_code=error_code,
    )
    session.add(row)
    session.flush()
    return row


def list_product_rows_by_source(
    session: Session,
    *,
    source: str,
) -> list[ProductRow]:
    return list(
        session.scalars(
            select(ProductRow)
            .where(ProductRow.source == source)
            .order_by(ProductRow.identity_key)
        )
    )


def find_product_row(
    session: Session,
    *,
    source: str,
    canonical_product_url: str | None = None,
    source_record_id: str | None = None,
    identity_key: str | None = None,
    for_update: bool = False,
) -> ProductRow | None:
    """Find one current product by its primary identity or a current locator.

    ``identity_key`` and ``source_record_id`` target the primary M2/M3 identity.
    A URL-only lookup intentionally queries ``canonical_product_url`` directly: a
    product may use ``id:<source_record_id>`` as its primary identity while still
    remaining addressable by its current canonical URL.

    M6 uses ``for_update=True`` inside state-transition transactions. On
    PostgreSQL this serializes concurrent transitions for an existing product, so
    every worker computes its decision from the latest committed trusted state.
    Read-only CLI lookups keep the default non-locking behavior.
    """

    statement = None
    if identity_key is not None:
        statement = select(ProductRow).where(
            ProductRow.source == source,
            ProductRow.identity_key == identity_key,
        )
    elif source_record_id is not None:
        statement = select(ProductRow).where(
            ProductRow.source == source,
            ProductRow.identity_key == f"id:{source_record_id}",
        )
    elif canonical_product_url is not None:
        statement = select(ProductRow).where(
            ProductRow.source == source,
            ProductRow.canonical_product_url == canonical_product_url,
        )

    if statement is None:
        return None

    if for_update:
        statement = statement.with_for_update()

    return session.scalar(statement)


def list_product_history_rows(
    session: Session,
    *,
    product_id: int,
) -> list[ProductHistoryRow]:
    return list(
        session.scalars(
            select(ProductHistoryRow)
            .where(ProductHistoryRow.product_id == product_id)
            .order_by(ProductHistoryRow.id)
        )
    )


def row_to_current_state(row: ProductRow) -> CurrentProductState:
    return CurrentProductState(
        identity=ProductIdentity(
            source=row.source,
            canonical_product_url=row.canonical_product_url,
            source_record_id=row.source_record_id,
        ),
        title=row.title,
        price=Decimal(row.price),
        compare_at_price=(
            Decimal(row.compare_at_price) if row.compare_at_price is not None else None
        ),
        currency=Currency(row.currency),
        availability=Availability(row.availability),
        quantity=row.quantity,
        category=row.category,
        sku=row.sku,
        categories=tuple(row.categories or []),
        variants=tuple(_variant_state_from_payload(item) for item in (row.variants or [])),
        source_url=row.source_url,
        observed_at=row.observed_at,
        updated_at=row.updated_at,
        presence_status=ProductPresenceStatus(row.presence_status),
        presence_observed_at=row.presence_observed_at,
    )


def persist_product_observation(
    session: Session,
    *,
    observation: ProductObservation,
    normalized: ProductNormalizedData,
    transition: StateTransitionResult,
) -> ProductObservationRow:
    key = _identity_key(
        canonical_product_url=normalized.canonical_product_url,
        source_record_id=normalized.source_record_id,
    )
    if key is None:
        key = (
            f"rejected:{observation.source_record_id_raw or observation.source_url}:"
            f"{observation.title_raw or ''}"
        )

    existing = session.scalar(
        select(ProductObservationRow).where(
            ProductObservationRow.evidence_id == observation.evidence_id,
            ProductObservationRow.extractor_version == observation.extractor_version,
            ProductObservationRow.identity_key == key,
        )
    )
    if existing is not None:
        return existing

    row = ProductObservationRow(
        evidence_id=observation.evidence_id,
        extractor_version=observation.extractor_version,
        source=observation.source,
        identity_key=key,
        source_record_id=normalized.source_record_id,
        source_url=observation.source_url,
        observed_at=observation.observed_at,
        title_raw=observation.title_raw,
        price_raw=observation.price_raw,
        compare_at_price_raw=observation.compare_at_price_raw,
        currency_raw=observation.currency_raw,
        availability_raw=observation.availability_raw,
        category_raw=observation.category_raw,
        sku_raw=observation.sku_raw,
        categories_raw=list(observation.categories_raw),
        variants_raw=[_raw_variant_payload(item) for item in observation.variants_raw],
        canonical_product_url=normalized.canonical_product_url,
        title=normalized.title,
        price=normalized.price,
        compare_at_price=normalized.compare_at_price,
        currency=normalized.currency.value if normalized.currency is not None else None,
        availability=(
            normalized.availability.value if normalized.availability is not None else None
        ),
        quantity=normalized.quantity,
        category=normalized.category,
        sku=normalized.sku,
        categories=list(normalized.categories),
        variants=[_normalized_variant_payload(item) for item in normalized.variants],
        state_decision=transition.decision.value,
        validation_errors=[error.value for error in transition.validation_errors],
    )
    session.add(row)
    session.flush()
    return row


def _state_snapshot(state: CurrentProductState) -> dict[str, object]:
    return {
        "source": state.identity.source,
        "identity_key": state.identity.key,
        "source_record_id": state.identity.source_record_id,
        "canonical_product_url": state.identity.canonical_product_url,
        "title": state.title,
        "price": str(state.price),
        "compare_at_price": (
            str(state.compare_at_price) if state.compare_at_price is not None else None
        ),
        "currency": state.currency.value,
        "availability": state.availability.value,
        "quantity": state.quantity,
        "category": state.category,
        "sku": state.sku,
        "categories": list(state.categories),
        "variants": [_state_variant_payload(item) for item in state.variants],
        "source_url": state.source_url,
        "observed_at": state.observed_at.isoformat(),
        "updated_at": state.updated_at.isoformat(),
        "presence_status": state.presence_status.value,
        "presence_observed_at": (
            state.presence_observed_at.isoformat()
            if state.presence_observed_at is not None
            else state.observed_at.isoformat()
        ),
    }


def _create_product_row(
    session: Session,
    *,
    state: CurrentProductState,
    observation_id: int,
) -> ProductRow:
    row = ProductRow(
        source=state.identity.source,
        identity_key=state.identity.key,
        source_record_id=state.identity.source_record_id,
        canonical_product_url=state.identity.canonical_product_url,
        title=state.title,
        price=state.price,
        compare_at_price=state.compare_at_price,
        currency=state.currency.value,
        availability=state.availability.value,
        quantity=state.quantity,
        category=state.category,
        sku=state.sku,
        categories=list(state.categories),
        variants=[_state_variant_payload(item) for item in state.variants],
        source_url=state.source_url,
        observed_at=state.observed_at,
        updated_at=state.updated_at,
        presence_status=state.presence_status.value,
        presence_observed_at=state.presence_observed_at or state.observed_at,
        accepted_observation_id=observation_id,
    )
    session.add(row)
    session.flush()
    return row


def _update_product_row(
    row: ProductRow,
    *,
    state: CurrentProductState,
    observation_id: int | None,
) -> None:
    row.identity_key = state.identity.key
    row.source_record_id = state.identity.source_record_id
    row.canonical_product_url = state.identity.canonical_product_url
    row.title = state.title
    row.price = state.price
    row.compare_at_price = state.compare_at_price
    row.currency = state.currency.value
    row.availability = state.availability.value
    row.quantity = state.quantity
    row.category = state.category
    row.sku = state.sku
    row.categories = list(state.categories)
    row.variants = [_state_variant_payload(item) for item in state.variants]
    row.source_url = state.source_url
    row.observed_at = state.observed_at
    row.updated_at = state.updated_at
    row.presence_status = state.presence_status.value
    row.presence_observed_at = state.presence_observed_at or state.observed_at
    if observation_id is not None:
        row.accepted_observation_id = observation_id


def _append_history(
    session: Session,
    *,
    product_id: int,
    observation_id: int | None,
    catalog_run_id: int | None,
    history: ProductHistoryEntry,
) -> ProductHistoryRow:
    row = ProductHistoryRow(
        source=history.identity.source,
        identity_key=history.identity.key,
        product_id=product_id,
        observation_id=observation_id,
        catalog_run_id=catalog_run_id,
        decision=history.decision.value,
        previous_state=(
            _state_snapshot(history.previous_state)
            if history.previous_state is not None
            else None
        ),
        new_state=_state_snapshot(history.new_state),
        changed_at=history.changed_at,
    )
    session.add(row)
    session.flush()
    return row


def apply_state_transition(
    session: Session,
    *,
    existing_product: ProductRow | None = None,
    transition: StateTransitionResult,
    observation_id: int | None,
    catalog_run_id: int | None = None,
    existing_book: ProductRow | None = None,
) -> ProductRow | None:
    if existing_product is None:
        existing_product = existing_book

    if transition.decision in {StateDecision.REJECT, StateDecision.STALE}:
        return existing_product

    if transition.decision == StateDecision.NO_CHANGE:
        if existing_product is not None and transition.current_state is not None:
            # M8: equivalent observations still advance presence freshness. This
            # metadata update is intentionally not a business-history entry.
            existing_product.presence_status = transition.current_state.presence_status.value
            existing_product.presence_observed_at = (
                transition.current_state.presence_observed_at
                or transition.current_state.observed_at
            )
            session.flush()
        return existing_product

    if transition.current_state is None or transition.history_entry is None:
        raise ValueError("state-changing transition requires current state and history")

    if transition.decision == StateDecision.CREATE:
        if existing_product is not None:
            raise ValueError("CREATE transition cannot be applied to an existing product")
        if observation_id is None:
            raise ValueError("CREATE transition requires product observation provenance")
        product_row = _create_product_row(
            session,
            state=transition.current_state,
            observation_id=observation_id,
        )
        _append_history(
            session,
            product_id=product_row.id,
            observation_id=observation_id,
            catalog_run_id=None,
            history=transition.history_entry,
        )
        return product_row

    if transition.decision in {StateDecision.UPDATE, StateDecision.REAPPEARED}:
        if existing_product is None:
            raise ValueError(f"{transition.decision.value} requires an existing product")
        if observation_id is None:
            raise ValueError(f"{transition.decision.value} requires product observation provenance")
        _update_product_row(
            existing_product,
            state=transition.current_state,
            observation_id=observation_id,
        )
        session.flush()
        _append_history(
            session,
            product_id=existing_product.id,
            observation_id=observation_id,
            catalog_run_id=None,
            history=transition.history_entry,
        )
        return existing_product

    if transition.decision == StateDecision.DISAPPEARED:
        if existing_product is None:
            raise ValueError("DISAPPEARED transition requires an existing product")
        if catalog_run_id is None:
            raise ValueError("DISAPPEARED transition requires complete catalog provenance")
        _update_product_row(
            existing_product,
            state=transition.current_state,
            observation_id=None,
        )
        session.flush()
        _append_history(
            session,
            product_id=existing_product.id,
            observation_id=None,
            catalog_run_id=catalog_run_id,
            history=transition.history_entry,
        )
        return existing_product

    raise ValueError(f"unsupported state decision: {transition.decision}")


# M0 compatibility API aliases.
def find_book_row(
    session: Session,
    *,
    source: str,
    canonical_product_url: str | None,
) -> ProductRow | None:
    return find_product_row(
        session,
        source=source,
        canonical_product_url=canonical_product_url,
    )


def list_book_history_rows(session: Session, *, book_id: int) -> list[ProductHistoryRow]:
    return list_product_history_rows(session, product_id=book_id)


def persist_book_observation(
    session: Session,
    *,
    observation,
    normalized,
    transition,
) -> ProductObservationRow:
    return persist_product_observation(
        session,
        observation=observation,
        normalized=normalized,
        transition=transition,
    )
