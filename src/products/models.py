from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class Currency(str, Enum):
    GBP = "GBP"
    USD = "USD"


class Availability(str, Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class StateDecision(str, Enum):
    CREATE = "CREATE"
    NO_CHANGE = "NO_CHANGE"
    UPDATE = "UPDATE"
    STALE = "STALE"
    REJECT = "REJECT"


class ValidationErrorCode(str, Enum):
    MISSING_TITLE = "MISSING_TITLE"
    MISSING_PRICE = "MISSING_PRICE"
    NEGATIVE_PRICE = "NEGATIVE_PRICE"
    NEGATIVE_COMPARE_AT_PRICE = "NEGATIVE_COMPARE_AT_PRICE"
    COMPARE_AT_BELOW_PRICE = "COMPARE_AT_BELOW_PRICE"
    MISSING_CURRENCY = "MISSING_CURRENCY"
    UNKNOWN_AVAILABILITY = "UNKNOWN_AVAILABILITY"
    NEGATIVE_QUANTITY = "NEGATIVE_QUANTITY"
    INCONSISTENT_AVAILABILITY_QUANTITY = "INCONSISTENT_AVAILABILITY_QUANTITY"
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
    INVALID_CANONICAL_URL = "INVALID_CANONICAL_URL"
    MISSING_IDENTITY = "MISSING_IDENTITY"
    MISSING_VARIANT_IDENTITY = "MISSING_VARIANT_IDENTITY"
    DUPLICATE_VARIANT_IDENTITY = "DUPLICATE_VARIANT_IDENTITY"
    INVALID_VARIANT_PRICE = "INVALID_VARIANT_PRICE"
    INVALID_VARIANT_AVAILABILITY = "INVALID_VARIANT_AVAILABILITY"


@dataclass(frozen=True)
class ProductVariantObservation:
    sku_raw: str | None
    price_raw: str | None
    availability_raw: str | None
    options_raw: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ProductVariantNormalizedData:
    key: str | None
    sku: str | None
    options: tuple[tuple[str, str], ...]
    price: Decimal | None
    availability: Availability | None


@dataclass(frozen=True)
class ValidatedProductVariant:
    key: str
    sku: str | None
    options: tuple[tuple[str, str], ...]
    price: Decimal
    availability: Availability


@dataclass(frozen=True)
class CurrentProductVariantState:
    key: str
    sku: str | None
    options: tuple[tuple[str, str], ...]
    price: Decimal
    availability: Availability


@dataclass(frozen=True)
class ProductObservation:
    evidence_id: str
    extractor_version: str
    source: str
    source_url: str
    observed_at: datetime
    title_raw: str | None
    price_raw: str | None
    availability_raw: str | None
    category_raw: str | None
    currency_raw: str | None = None
    source_record_id_raw: str | None = None
    canonical_product_url_raw: str | None = None
    compare_at_price_raw: str | None = None
    sku_raw: str | None = None
    categories_raw: tuple[str, ...] = ()
    variants_raw: tuple[ProductVariantObservation, ...] = ()


@dataclass(frozen=True)
class ProductNormalizedData:
    source: str
    canonical_product_url: str | None
    observed_at: datetime
    title: str | None
    price: Decimal | None
    currency: Currency | None
    availability: Availability | None
    quantity: int | None
    category: str | None
    source_url: str | None = None
    source_record_id: str | None = None
    compare_at_price: Decimal | None = None
    sku: str | None = None
    categories: tuple[str, ...] = ()
    variants: tuple[ProductVariantNormalizedData, ...] = ()


@dataclass(frozen=True)
class ProductIdentity:
    source: str
    canonical_product_url: str | None = None
    source_record_id: str | None = None

    @property
    def key(self) -> str:
        if self.source_record_id:
            return f"id:{self.source_record_id}"
        if self.canonical_product_url:
            return f"url:{self.canonical_product_url}"
        raise ValueError("product identity requires source_record_id or canonical_product_url")


@dataclass(frozen=True)
class ValidatedProduct:
    identity: ProductIdentity
    title: str
    price: Decimal
    currency: Currency
    availability: Availability
    quantity: int | None
    category: str | None
    source_url: str
    observed_at: datetime
    compare_at_price: Decimal | None = None
    sku: str | None = None
    categories: tuple[str, ...] = ()
    variants: tuple[ValidatedProductVariant, ...] = ()


@dataclass(frozen=True)
class CurrentProductState:
    identity: ProductIdentity
    title: str
    price: Decimal
    currency: Currency
    availability: Availability
    quantity: int | None
    category: str | None
    source_url: str
    observed_at: datetime
    updated_at: datetime
    compare_at_price: Decimal | None = None
    sku: str | None = None
    categories: tuple[str, ...] = ()
    variants: tuple[CurrentProductVariantState, ...] = ()


@dataclass(frozen=True)
class ProductHistoryEntry:
    identity: ProductIdentity
    decision: StateDecision
    previous_state: CurrentProductState | None
    new_state: CurrentProductState
    changed_at: datetime


@dataclass(frozen=True)
class ValidationResult:
    product: ValidatedProduct | None
    errors: tuple[ValidationErrorCode, ...]

    @property
    def is_valid(self) -> bool:
        return self.product is not None and not self.errors

    @property
    def book(self) -> ValidatedProduct | None:
        """M0 compatibility alias for the former book-specific contract."""
        return self.product


@dataclass(frozen=True)
class StateTransitionResult:
    decision: StateDecision
    current_state: CurrentProductState | None
    history_entry: ProductHistoryEntry | None
    validation_errors: tuple[ValidationErrorCode, ...] = ()
