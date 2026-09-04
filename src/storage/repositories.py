from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.acquisition.models import RawEvidence
from src.products.models import (
    Availability,
    Currency,
    CurrentProductState,
    ProductHistoryEntry,
    ProductIdentity,
    ProductNormalizedData,
    ProductObservation,
    StateDecision,
    StateTransitionResult,
)

from .models import (
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


def find_product_row(
    session: Session,
    *,
    source: str,
    canonical_product_url: str | None = None,
    source_record_id: str | None = None,
    identity_key: str | None = None,
) -> ProductRow | None:
    key = identity_key or _identity_key(
        canonical_product_url=canonical_product_url,
        source_record_id=source_record_id,
    )
    if key is None:
        return None

    return session.scalar(
        select(ProductRow).where(
            ProductRow.source == source,
            ProductRow.identity_key == key,
        )
    )


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
        currency=Currency(row.currency),
        availability=Availability(row.availability),
        quantity=row.quantity,
        category=row.category,
        source_url=row.source_url,
        observed_at=row.observed_at,
        updated_at=row.updated_at,
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
    # Invalid identity still needs a deterministic observation key so the
    # rejected observation can be traced without colliding with another record
    # from the same multi-record evidence payload.
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
        currency_raw=observation.currency_raw,
        availability_raw=observation.availability_raw,
        category_raw=observation.category_raw,
        canonical_product_url=normalized.canonical_product_url,
        title=normalized.title,
        price=normalized.price,
        currency=normalized.currency.value if normalized.currency is not None else None,
        availability=(
            normalized.availability.value if normalized.availability is not None else None
        ),
        quantity=normalized.quantity,
        category=normalized.category,
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
        "currency": state.currency.value,
        "availability": state.availability.value,
        "quantity": state.quantity,
        "category": state.category,
        "source_url": state.source_url,
        "observed_at": state.observed_at.isoformat(),
        "updated_at": state.updated_at.isoformat(),
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
        currency=state.currency.value,
        availability=state.availability.value,
        quantity=state.quantity,
        category=state.category,
        source_url=state.source_url,
        observed_at=state.observed_at,
        updated_at=state.updated_at,
        accepted_observation_id=observation_id,
    )
    session.add(row)
    session.flush()
    return row


def _update_product_row(
    row: ProductRow,
    *,
    state: CurrentProductState,
    observation_id: int,
) -> None:
    row.identity_key = state.identity.key
    row.source_record_id = state.identity.source_record_id
    row.canonical_product_url = state.identity.canonical_product_url
    row.title = state.title
    row.price = state.price
    row.currency = state.currency.value
    row.availability = state.availability.value
    row.quantity = state.quantity
    row.category = state.category
    row.source_url = state.source_url
    row.observed_at = state.observed_at
    row.updated_at = state.updated_at
    row.accepted_observation_id = observation_id


def _append_history(
    session: Session,
    *,
    product_id: int,
    observation_id: int,
    history: ProductHistoryEntry,
) -> ProductHistoryRow:
    row = ProductHistoryRow(
        product_id=product_id,
        observation_id=observation_id,
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
    observation_id: int,
    existing_book: ProductRow | None = None,
) -> ProductRow | None:
    if existing_product is None:
        existing_product = existing_book

    if transition.decision in {StateDecision.REJECT, StateDecision.NO_CHANGE}:
        return existing_product

    if transition.current_state is None or transition.history_entry is None:
        raise ValueError("state-changing transition requires current state and history")

    if transition.decision == StateDecision.CREATE:
        if existing_product is not None:
            raise ValueError("CREATE transition cannot be applied to an existing product")
        product_row = _create_product_row(
            session,
            state=transition.current_state,
            observation_id=observation_id,
        )
        _append_history(
            session,
            product_id=product_row.id,
            observation_id=observation_id,
            history=transition.history_entry,
        )
        return product_row

    if transition.decision == StateDecision.UPDATE:
        if existing_product is None:
            raise ValueError("UPDATE transition requires an existing product")
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
