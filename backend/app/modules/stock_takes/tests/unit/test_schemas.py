"""Unit tests for stock takes Pydantic schemas."""

from uuid import uuid4

import pytest

from app.modules.stock_takes.models import StockTakeStatus
from app.modules.stock_takes.schemas import (
    StockTakeComplete,
    StockTakeCreate,
    StockTakeItemCountUpdate,
    StockTakeItemCreate,
    StockTakeItemUpdate,
    StockTakeStatusUpdate,
    StockTakeUpdate,
)


@pytest.mark.unit
class TestStockTakeSchemas:
    """Tests for stock take schemas."""

    def test_stock_take_create_valid(self) -> None:
        storage_id = uuid4()
        payload = {
            'name': 'January stock take',
            'description': 'Freezer stock take',
            'location_id': storage_id,
        }

        stock_take = StockTakeCreate(**payload)

        assert stock_take.name == 'January stock take'
        assert stock_take.description == 'Freezer stock take'
        assert stock_take.location_id == storage_id

    def test_stock_take_update_partial(self) -> None:
        stock_take_update = StockTakeUpdate(name='Updated name')

        assert stock_take_update.name == 'Updated name'
        assert stock_take_update.description is None
        assert stock_take_update.status is None

    def test_stock_take_status_update(self) -> None:
        status_update = StockTakeStatusUpdate(status=StockTakeStatus.COMPLETED)

        assert status_update.status == StockTakeStatus.COMPLETED

    def test_stock_take_item_create_valid(self) -> None:
        item_id = uuid4()
        payload = {
            'item_id': item_id,
            'item_name': 'Milk',
            'item_brand': 'Mlekovita',
            'item_unit': 'pcs',
            'system_quantity': 5,
            'counted_quantity': 5,
        }

        stock_take_item = StockTakeItemCreate(**payload)

        assert stock_take_item.item_id == item_id
        assert stock_take_item.item_name == 'Milk'
        assert stock_take_item.system_quantity == 5
        assert stock_take_item.counted_quantity == 5

    def test_stock_take_item_create_without_item_id(self) -> None:
        stock_take_item = StockTakeItemCreate(
            item_name='Unknown product',
            system_quantity=None,
            counted_quantity=1,
        )

        assert stock_take_item.item_id is None
        assert stock_take_item.item_name == 'Unknown product'

    def test_stock_take_item_update_partial(self) -> None:
        item_update = StockTakeItemUpdate(counted_quantity=10)

        assert item_update.counted_quantity == 10
        assert item_update.shelf_location is None
        assert item_update.notes is None

    def test_stock_take_item_count_update(self) -> None:
        count_update = StockTakeItemCountUpdate(
            counted_quantity=7,
            shelf_location='Shelf 2',
            notes='Found extra units',
        )

        assert count_update.counted_quantity == 7
        assert count_update.shelf_location == 'Shelf 2'
        assert count_update.notes == 'Found extra units'

    def test_stock_take_complete_schema(self) -> None:
        complete = StockTakeComplete(
            apply_adjustments=True, notes='Stock take completed successfully'
        )

        assert complete.apply_adjustments is True
        assert complete.notes == 'Stock take completed successfully'

    def test_stock_take_complete_default_values(self) -> None:
        complete = StockTakeComplete()

        assert complete.apply_adjustments is True
        assert complete.notes is None


@pytest.mark.unit
class TestStockTakeSchemaValidation:
    """Validation cases for stock takes schemas."""

    def test_stock_take_item_counted_quantity_validation_negative(self) -> None:
        with pytest.raises(ValueError):
            StockTakeItemCreate(
                item_name='Test',
                counted_quantity=-1,
            )

    def test_stock_take_name_validation_empty(self) -> None:
        with pytest.raises(ValueError):
            StockTakeCreate(name='', location_id=uuid4())

    def test_stock_take_name_validation_too_long(self) -> None:
        with pytest.raises(ValueError):
            StockTakeCreate(name='a' * 256, location_id=uuid4())
