from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .models import (
    CurrentProductState,
    CurrentProductVariantState,
    ProductHistoryEntry,
    ProductNormalizedData,
    ProductPresenceStatus,
    StateDecision,
    StateTransitionResult,
    ValidatedProduct,
)
from .validation import validate_product


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _presence_time(state: CurrentProductState) -> datetime:
    return state.presence_observed_at or state.observed_at


def _canonical_categories(values: tuple[str, ...]) -> tuple[str, ...]:
    """Compare category membership, not source presentation order."""
    return tuple(sorted(values, key=lambda value: (value.casefold(), value)))


def _canonical_options(
    values: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """Variant option order is not semantic when option names are explicit."""
    return tuple(
        sorted(values, key=lambda item: (item[0].casefold(), item[1].casefold(), item))
    )


def _canonical_variant_state(
    variant: CurrentProductVariantState,
) -> tuple[object, ...]:
    return (
        variant.key,
        variant.sku,
        _canonical_options(variant.options),
        variant.price,
        variant.availability,
    )


def _canonical_current_variants(
    variants: tuple[CurrentProductVariantState, ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (_canonical_variant_state(item) for item in variants),
            key=lambda item: str(item[0]),
        )
    )


def _canonical_incoming_variants(
    product: ValidatedProduct,
) -> tuple[tuple[object, ...], ...]:
    values = tuple(
        (
            variant.key,
            variant.sku,
            _canonical_options(variant.options),
            variant.price,
            variant.availability,
        )
        for variant in product.variants
    )
    return tuple(sorted(values, key=lambda item: str(item[0])))


def _as_current_state(
    product: ValidatedProduct,
    *,
    updated_at: datetime,
) -> CurrentProductState:
    return CurrentProductState(
        identity=product.identity,
        title=product.title,
        price=product.price,
        compare_at_price=product.compare_at_price,
        currency=product.currency,
        availability=product.availability,
        quantity=product.quantity,
        category=product.category,
        sku=product.sku,
        categories=product.categories,
        variants=tuple(
            CurrentProductVariantState(
                key=variant.key,
                sku=variant.sku,
                options=variant.options,
                price=variant.price,
                availability=variant.availability,
            )
            for variant in product.variants
        ),
        source_url=product.source_url,
        observed_at=product.observed_at,
        updated_at=updated_at,
        presence_status=ProductPresenceStatus.ACTIVE,
        presence_observed_at=product.observed_at,
    )


def _same_business_state(
    current: CurrentProductState,
    incoming: ValidatedProduct,
) -> bool:
    return (
        current.identity == incoming.identity
        and current.title == incoming.title
        and current.price == incoming.price
        and current.compare_at_price == incoming.compare_at_price
        and current.currency == incoming.currency
        and current.availability == incoming.availability
        and current.quantity == incoming.quantity
        and current.category == incoming.category
        and current.sku == incoming.sku
        and _canonical_categories(current.categories)
        == _canonical_categories(incoming.categories)
        and _canonical_current_variants(current.variants)
        == _canonical_incoming_variants(incoming)
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

    # M8: freshness is about the latest accepted evidence of presence/absence,
    # not only the observation that last changed business fields. A newer
    # NO_CHANGE observation still proves the product existed at that later time.
    if _as_utc(incoming.observed_at) < _as_utc(_presence_time(current)):
        return StateTransitionResult(
            decision=StateDecision.STALE,
            current_state=current,
            history_entry=None,
        )

    if current.presence_status == ProductPresenceStatus.DISAPPEARED:
        new_state = _as_current_state(incoming, updated_at=changed_at)
        history = ProductHistoryEntry(
            identity=incoming.identity,
            decision=StateDecision.REAPPEARED,
            previous_state=current,
            new_state=new_state,
            changed_at=changed_at,
        )
        return StateTransitionResult(
            decision=StateDecision.REAPPEARED,
            current_state=new_state,
            history_entry=history,
        )

    if _same_business_state(current, incoming):
        # No business-history entry, but advance presence freshness. This prevents
        # a delayed older complete-catalog snapshot from falsely disappearing a
        # product that was observed unchanged more recently.
        refreshed = replace(
            current,
            presence_status=ProductPresenceStatus.ACTIVE,
            presence_observed_at=incoming.observed_at,
        )
        return StateTransitionResult(
            decision=StateDecision.NO_CHANGE,
            current_state=refreshed,
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


def transition_product_absence(
    current: CurrentProductState,
    *,
    observed_at: datetime,
    changed_at: datetime | None = None,
) -> StateTransitionResult:
    """Apply absence only when a complete catalog run proves scope coverage.

    This function does not decide whether a catalog is complete; that belongs to
    the catalog/acquisition boundary. It only translates a trusted complete-run
    absence into product presence state.
    """

    changed_at = changed_at or _utc_now()
    if _as_utc(observed_at) < _as_utc(_presence_time(current)):
        return StateTransitionResult(
            decision=StateDecision.STALE,
            current_state=current,
            history_entry=None,
        )

    if current.presence_status == ProductPresenceStatus.DISAPPEARED:
        refreshed = replace(current, presence_observed_at=observed_at)
        return StateTransitionResult(
            decision=StateDecision.NO_CHANGE,
            current_state=refreshed,
            history_entry=None,
        )

    disappeared = replace(
        current,
        presence_status=ProductPresenceStatus.DISAPPEARED,
        presence_observed_at=observed_at,
        updated_at=changed_at,
    )
    history = ProductHistoryEntry(
        identity=current.identity,
        decision=StateDecision.DISAPPEARED,
        previous_state=current,
        new_state=disappeared,
        changed_at=changed_at,
    )
    return StateTransitionResult(
        decision=StateDecision.DISAPPEARED,
        current_state=disappeared,
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
