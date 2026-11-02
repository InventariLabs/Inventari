"""
Unit tests for depreciation_service async functions using mock core_api.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.equipment.depreciation_service import (
    _MAX_EQUIPMENT_ITEMS,
    ZERO,
    get_asset_valuation_async,
    get_fleet_valuation_async,
)


def _mock_item(
    *,
    name: str = 'Test Item',
    purchase_price: Any = None,
    serial_number: str | None = None,
    purchase_date: str | None = None,
    useful_life_years: int | None = None,
    equipment_status: str = 'AVAILABLE',
    category_name: str = 'Laptops',
    category_code: str | None = 'LAPTOP',
    currency: str | None = None,
) -> MagicMock:
    item = MagicMock()
    item.id = uuid4()
    item.name = name
    item.purchase_price = purchase_price
    item.serial_number = serial_number
    item.currency = currency
    meta: dict[str, dict[str, Any]] = {
        'equipment': {'equipment_status': equipment_status}
    }
    if purchase_date:
        meta['equipment']['purchase_date'] = purchase_date
    if useful_life_years:
        meta['equipment']['useful_life_years'] = useful_life_years
    item.meta_data = meta
    cat = MagicMock()
    cat.name = category_name
    # the valuation payload carries the declaration code so the UI
    # can translate the row label; a bare MagicMock would not validate.
    cat.code = category_code
    cat.field_definitions = []
    item.category = cat
    return item


def _mock_category(context_tag: str = 'equipment') -> MagicMock:
    cat = MagicMock()
    cat.id = uuid4()
    cat.context_tag = context_tag
    cat.field_definitions = []
    return cat


def _mock_core_context(mock_core: Any, *, org_currency: str = 'USD') -> None:
    """Stub the facade calls added by /."""
    org = MagicMock()
    org.currency = org_currency
    mock_core.settings.get_async = AsyncMock(return_value={})
    mock_core.organizations.get_async = AsyncMock(return_value=org)
    # The book value is struck as at the organization's day, so the facade
    # has to answer that question here too — a bare MagicMock is not
    # awaitable, and a book value has to be dated to something real.
    mock_core.organizations.today_async = AsyncMock(return_value=date.today())


@pytest.mark.unit
class TestGetAssetValuation:
    @patch('app.modules.equipment.depreciation_service.core_api')
    async def test_item_not_found(self, mock_core: Any) -> None:
        mock_core.items.get_any_async = AsyncMock(return_value=None)
        db = MagicMock()
        org_id = uuid4()
        item_id = uuid4()
        result = await get_asset_valuation_async(db, org_id, item_id)
        assert result is None

    @patch('app.modules.equipment.depreciation_service.core_api')
    async def test_item_with_purchase_price(self, mock_core: Any) -> None:
        _mock_core_context(mock_core)
        item = _mock_item(
            purchase_price=Decimal('1200.00'),
            purchase_date='2023-01-15',
        )
        mock_core.items.get_any_async = AsyncMock(return_value=item)
        db = MagicMock()
        org_id = uuid4()
        result = await get_asset_valuation_async(db, org_id, item.id)
        assert result is not None
        assert result['is_depreciable'] is True
        assert result['purchase_price'] == Decimal('1200.00')
        assert result['item_name'] == 'Test Item'

    @patch('app.modules.equipment.depreciation_service.core_api')
    async def test_item_no_purchase_price(self, mock_core: Any) -> None:
        _mock_core_context(mock_core)
        item = _mock_item(purchase_price=None)
        mock_core.items.get_any_async = AsyncMock(return_value=item)
        db = MagicMock()
        org_id = uuid4()
        result = await get_asset_valuation_async(db, org_id, item.id)
        assert result is not None
        assert result['is_depreciable'] is False

    @patch('app.modules.equipment.depreciation_service.core_api')
    async def test_item_no_meta_data(self, mock_core: Any) -> None:
        _mock_core_context(mock_core)
        item = _mock_item()
        item.meta_data = None
        item.purchase_price = Decimal('500')
        mock_core.items.get_any_async = AsyncMock(return_value=item)
        db = MagicMock()
        org_id = uuid4()
        result = await get_asset_valuation_async(db, org_id, item.id)
        assert result is not None


@pytest.mark.unit
class TestGetFleetValuation:
    @pytest.mark.parametrize('status_value', [None, '', 'UNKNOWN'])
    @patch('app.modules.equipment.depreciation_service.core_api')
    async def test_asset_without_status_is_valued_and_flagged(
        self, mock_core: Any, status_value: str | None
    ) -> None:
        _mock_core_context(mock_core)
        mock_core.categories.list_async = AsyncMock(return_value=[])
        item = _mock_item(purchase_price=Decimal('1200'))
        item.meta_data = {'equipment': {'equipment_status': status_value}}
        mock_core.items.list_async = AsyncMock(return_value=[item])
        result = await get_fleet_valuation_async(MagicMock(), uuid4())
        assert result.asset_count == 1
        assert result.total_purchase_value == Decimal('1200')
        assert result.no_status_count == 1
        assert [(asset.id, asset.name) for asset in result.no_status_assets] == [
            (item.id, item.name)
        ]

    @patch('app.modules.equipment.depreciation_service.core_api')
    async def test_no_equipment_items(self, mock_core: Any) -> None:
        _mock_core_context(mock_core)
        mock_core.categories.list_async = AsyncMock(return_value=[])
        mock_core.items.list_async = AsyncMock(return_value=[])
        db = MagicMock()
        org_id = uuid4()
        result = await get_fleet_valuation_async(db, org_id)
        assert result.asset_count == 0
        assert result.total_purchase_value == ZERO
        assert result.by_category == []
        mock_core.items.list_async.assert_awaited_once_with(
            db, org_id, context_tag='equipment', limit=_MAX_EQUIPMENT_ITEMS
        )

    @patch('app.modules.equipment.depreciation_service.core_api')
    async def test_with_equipment_items(self, mock_core: Any) -> None:
        _mock_core_context(mock_core)
        cat = _mock_category('equipment')
        mock_core.categories.list_async = AsyncMock(return_value=[cat])
        item = _mock_item(
            purchase_price=Decimal('2000.00'),
            purchase_date='2022-06-01',
        )
        mock_core.items.list_async = AsyncMock(return_value=[item])
        db = MagicMock()
        org_id = uuid4()
        result = await get_fleet_valuation_async(db, org_id)
        assert result.asset_count == 1
        assert result.total_purchase_value == Decimal('2000.00')
        assert result.total_book_value >= ZERO
        assert len(result.by_category) == 1

    @patch('app.modules.equipment.depreciation_service.core_api')
    async def test_skips_retired_items(self, mock_core: Any) -> None:
        _mock_core_context(mock_core)
        cat = _mock_category('equipment')
        mock_core.categories.list_async = AsyncMock(return_value=[cat])
        item = _mock_item(
            purchase_price=Decimal('1000.00'),
            equipment_status='RETIRED',
        )
        mock_core.items.list_async = AsyncMock(return_value=[item])
        db = MagicMock()
        org_id = uuid4()
        result = await get_fleet_valuation_async(db, org_id)
        assert result.asset_count == 0
        assert result.total_purchase_value == ZERO
        # A retired asset is out of the valuation by decision, not by
        # accident — the register still holds it, and a count that loses it
        # silently leaves the reader no way to reconcile this number against
        # the categories catalogue's.
        assert result.excluded_count == 1

    @patch('app.modules.equipment.depreciation_service.core_api')
    async def test_skips_items_without_price(self, mock_core: Any) -> None:
        _mock_core_context(mock_core)
        cat = _mock_category('equipment')
        mock_core.categories.list_async = AsyncMock(return_value=[cat])
        item = _mock_item(purchase_price=None)
        mock_core.items.list_async = AsyncMock(return_value=[item])
        db = MagicMock()
        org_id = uuid4()
        result = await get_fleet_valuation_async(db, org_id)
        assert result.asset_count == 0
        assert result.total_purchase_value == ZERO

    @patch('app.modules.equipment.depreciation_service.core_api')
    async def test_multiple_categories(self, mock_core: Any) -> None:
        _mock_core_context(mock_core)
        cat1 = _mock_category('equipment')
        cat2 = _mock_category('equipment')
        mock_core.categories.list_async = AsyncMock(return_value=[cat1, cat2])
        item1 = _mock_item(
            purchase_price=Decimal('1000.00'),
            purchase_date='2024-01-01',
            category_name='Laptops',
        )
        item2 = _mock_item(
            purchase_price=Decimal('500.00'),
            purchase_date='2024-06-01',
            category_name='Monitors',
        )
        mock_core.items.list_async = AsyncMock(return_value=[item1, item2])
        db = MagicMock()
        org_id = uuid4()
        result = await get_fleet_valuation_async(db, org_id)
        assert result.asset_count == 2
        assert result.total_purchase_value == Decimal('1500.00')
