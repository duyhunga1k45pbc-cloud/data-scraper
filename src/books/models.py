"""M0 compatibility names for the shared M1 product-domain contracts."""

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
    ValidatedProduct,
    ValidationErrorCode,
    ValidationResult,
)

BookObservation = ProductObservation
BookNormalizedData = ProductNormalizedData
BookIdentity = ProductIdentity
ValidatedBook = ValidatedProduct
CurrentBookState = CurrentProductState
BookHistoryEntry = ProductHistoryEntry

__all__ = [
    "Availability",
    "Currency",
    "StateDecision",
    "ValidationErrorCode",
    "BookObservation",
    "BookNormalizedData",
    "BookIdentity",
    "ValidatedBook",
    "CurrentBookState",
    "BookHistoryEntry",
    "ValidationResult",
    "StateTransitionResult",
]
