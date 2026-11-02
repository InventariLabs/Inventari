"""A cost layer carries no location, so the drain cannot lock per shelf.

ADR-020 records the lock in ``ValuationService._post_delivery_async`` as one
product in one organization — the narrowest row the table can name, because
``StockValuationLayer`` has no ``storage_location_id``. That premise is a
model fact rather than a convention, and this test pins it: if a location
ever lands on the layer, the lock can be narrowed and the ADR is due for
revision — not this test.
"""

from __future__ import annotations

import pytest

from app.models.stock_anchor import StockAnchor
from app.models.stock_valuation_layer import StockValuationLayer

pytestmark = pytest.mark.unit


def test_a_cost_layer_has_no_location_column() -> None:
    # A location on the layer means ADR-020 is due for revision, not that
    # this assertion is wrong.
    assert 'storage_location_id' not in StockValuationLayer.__table__.columns


def test_a_stock_anchor_names_its_location() -> None:
    """The contrast the decision rests on: the lock of stock is per shelf.

    A group of stock is locked by its anchor, one per product on a shelf in
    an organization; the shelf key exists there.
    """
    assert 'storage_location_id' in StockAnchor.__table__.columns


def test_the_layer_names_its_own_lock_key() -> None:
    """Product in organization — the grain the drain locks, and nothing finer."""
    columns = StockValuationLayer.__table__.columns
    assert 'organization_id' in columns
    assert 'product_template_id' in columns
