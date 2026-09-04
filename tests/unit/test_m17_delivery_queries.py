import pytest

from src.delivery.queries import MAX_PAGE_SIZE, _page


def test_m17_delivery_page_bounds_are_explicit():
    assert _page(1, 0) == (1, 0)
    assert _page(MAX_PAGE_SIZE, 5) == (MAX_PAGE_SIZE, 5)
    with pytest.raises(ValueError):
        _page(0, 0)
    with pytest.raises(ValueError):
        _page(MAX_PAGE_SIZE + 1, 0)
    with pytest.raises(ValueError):
        _page(10, -1)
