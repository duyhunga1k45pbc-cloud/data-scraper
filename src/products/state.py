from __future__ import annotations

from datetime import datetime, timezone

from .models import (
    CurrentProductState,
    ProductHistoryEntry,
    ProductNormalizedData,
    StateDecision,
    StateTransitionResult,
    ValidatedProduct,
)
from .validation import validate_product


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_current_state(
    product: ValidatedProduct,
    *,
    updated_at: datetime,
) -> CurrentProductState:
    return CurrentProductState(
        identity=product.identity,
        title=product.title,
        price=product.price,
        currency=product.currency,
        availability=product.availability,
        quantity=product.quantity,
        category=product.category,
        source_url=product.source_url,
        observed_at=product.observed_at,
        updated_at=updated_at,
    )


def _same_business_state(
    current: CurrentProductState,
    incoming: ValidatedProduct,
) -> bool:
    return (
        current.identity == incoming.identity
        and current.title == incoming.title
        and current.price == incoming.price
        and current.currency == incoming.currency
        and current.availability == incoming.availability
        and current.quantity == incoming.quantity
        and current.category == incoming.category
        and current.source_url == incoming.source_url
    )


def transition_validated_product(
    current: CurrentProductState | None,
    incoming: ValidatedProduct,
    *,
    changed_at: datetime | None = None,
) -> StateTransitionResult:
    changed_at = changed_at or _utc_now()

    if current is None:
        new_state = _as_current_state(incoming, updated_at=changed_at)
        history = ProductHistoryEntry(
            identity=incoming.identity,
            decision=StateDecision.CREATE,
            previous_state=None,
            new_state=new_state,
            changed_at=changed_at,
        )
        return StateTransitionResult(
            decision=StateDecision.CREATE,
            current_state=new_state,
            history_entry=history,
        )

    if current.identity != incoming.identity:
        raise ValueError("incoming product identity does not match current state identity")

    if _same_business_state(current, incoming):
        return StateTransitionResult(
            decision=StateDecision.NO_CHANGE,
            current_state=current,
            history_entry=None,
        )

    new_state = _as_current_state(incoming, updated_at=changed_at)
    history = ProductHistoryEntry(
        identity=incoming.identity,
        decision=StateDecision.UPDATE,
        previous_state=current,
        new_state=new_state,
        changed_at=changed_at,
    )
    return StateTransitionResult(
        decision=StateDecision.UPDATE,
        current_state=new_state,
        history_entry=history,
    )


def process_normalized_product(
    current: CurrentProductState | None,
    data: ProductNormalizedData,
    *,
    changed_at: datetime | None = None,
) -> StateTransitionResult:
    validation = validate_product(data)

    if not validation.is_valid:
        return StateTransitionResult(
            decision=StateDecision.REJECT,
            current_state=current,
            history_entry=None,
            validation_errors=validation.errors,
        )

    assert validation.product is not None
    return transition_validated_product(
        current,
        validation.product,
        changed_at=changed_at,
    )
