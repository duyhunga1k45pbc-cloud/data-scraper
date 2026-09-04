import os

import pytest

from src.products.models import StateDecision
from src.products.service import process_product_url


URL = "https://scrapeme.live/shop/Charizard/"


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1")
def test_live_scrapeme_reaches_shared_product_state_boundary() -> None:
    result = process_product_url(URL)

    assert result.evidence.status_code == 200
    assert result.observation.source == "scrapeme_live"
    assert result.normalized.title == "Charizard"
    assert result.normalized.price is not None
    assert result.normalized.availability is not None
    assert result.transition.decision == StateDecision.CREATE
    assert not result.transition.validation_errors
