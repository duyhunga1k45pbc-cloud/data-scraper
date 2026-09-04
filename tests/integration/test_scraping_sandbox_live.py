import os
from decimal import Decimal

import pytest

from src.products.service import process_product_url


URL = "https://scrapingsandbox.com/product/1"


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1")
def test_m3_live_richer_product_semantics_are_preserved() -> None:
    result = process_product_url(URL)

    assert result.observation.source == "scraping_sandbox"
    assert result.normalized.source_record_id == "1"
    assert result.transition.current_state is not None
    state = result.transition.current_state
    assert state.price == Decimal("155.62")
    assert state.compare_at_price == Decimal("206.69")
    assert state.sku == "SKU-HEA-0001"
    assert state.categories == ("Health",)
    assert len(state.variants) == 4
    assert {variant.availability.value for variant in state.variants} == {
        "IN_STOCK",
        "OUT_OF_STOCK",
    }
