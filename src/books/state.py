"""M0 compatibility wrapper around shared product state transitions."""

from src.products.state import (
    process_normalized_product,
    transition_validated_product,
)

process_normalized_book = process_normalized_product
transition_validated_book = transition_validated_product

__all__ = ["process_normalized_book", "transition_validated_book"]
