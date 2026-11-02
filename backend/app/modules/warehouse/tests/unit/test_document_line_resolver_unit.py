from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.modules.warehouse.document_line_resolver import (
    _build_product_snapshot,
    build_document_line,
)


def _make_line_data(
    *,
    item_id: UUID | None = None,
    product_template_id: UUID | None = None,
    barcode: str | None = None,
    name: str | None = 'Test Item',
    brand: str | None = None,
    expected_quantity: Decimal = Decimal('10'),
    uom_id: UUID | None = None,
    unit_price: Decimal | None = None,
    tax_rate: Decimal | None = None,
    batch_number: str | None = None,
    serial_number: str | None = None,
    expiry_date: str | None = None,
    notes: str | None = None,
    source_po_line_id: UUID | None = None,
) -> MagicMock:
    data = MagicMock()
    data.item_id = item_id
    data.product_template_id = product_template_id
    data.barcode = barcode
    data.name = name
    data.brand = brand
    data.expected_quantity = expected_quantity
    data.uom_id = uom_id
    data.unit_price = unit_price
    data.tax_rate = tax_rate
    data.batch_number = batch_number
    data.serial_number = serial_number
    data.expiry_date = expiry_date
    data.notes = notes
    data.source_po_line_id = source_po_line_id
    return data


def _make_template(**kwargs: Any) -> MagicMock:
    tpl = MagicMock()
    tpl.id = kwargs.get('id', uuid4())
    tpl.name = kwargs.get('name', 'Test Product')
    tpl.brand = kwargs.get('brand', 'TestBrand')
    tpl.barcode = kwargs.get('barcode', '1234567890')
    tpl.sku = kwargs.get('sku', 'SKU-001')
    tpl.uom_id = kwargs.get('uom_id', uuid4())
    tpl.image_url = kwargs.get('image_url', 'http://img.png')
    return tpl


@pytest.mark.unit
class TestBuildProductSnapshot:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_template_and_no_barcode(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        line_data = _make_line_data(product_template_id=None, barcode=None)
        result = await _build_product_snapshot(db, line_data, org_id=org_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_looks_up_by_template_id(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        tpl = _make_template()
        line_data = _make_line_data(product_template_id=tpl.id)
        mock_core = MagicMock()
        mock_core.product_templates.get_async = AsyncMock(return_value=tpl)
        with patch('app.modules.warehouse.document_line_resolver.core_api', mock_core):
            result = await _build_product_snapshot(db, line_data, org_id=org_id)
        assert result is not None
        assert result['name'] == 'Test Product'
        assert result['brand'] == 'TestBrand'
        assert result['barcode'] == '1234567890'
        assert result['sku'] == 'SKU-001'
        assert result['uom_symbol'] is None

    @pytest.mark.asyncio
    async def test_looks_up_by_barcode_when_no_template_id(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        tpl = _make_template()
        line_data = _make_line_data(barcode='1234567890')
        mock_core = MagicMock()
        mock_core.product_templates.lookup_by_barcode_async = AsyncMock(
            return_value=tpl
        )
        with patch('app.modules.warehouse.document_line_resolver.core_api', mock_core):
            result = await _build_product_snapshot(db, line_data, org_id=org_id)
        assert result is not None
        assert result['name'] == 'Test Product'

    @pytest.mark.asyncio
    async def test_returns_none_when_template_not_found(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        line_data = _make_line_data(product_template_id=uuid4())
        mock_core = MagicMock()
        mock_core.product_templates.get_async = AsyncMock(return_value=None)
        with patch('app.modules.warehouse.document_line_resolver.core_api', mock_core):
            result = await _build_product_snapshot(db, line_data, org_id=org_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_org_id(self) -> None:
        db = MagicMock()
        line_data = _make_line_data(product_template_id=uuid4())
        result = await _build_product_snapshot(db, line_data, org_id=None)
        assert result is None


@pytest.mark.unit
class TestBuildDocumentLine:
    @pytest.mark.asyncio
    async def test_builds_line_without_db(self) -> None:
        line_data = _make_line_data(
            item_id=uuid4(),
            expected_quantity=Decimal('5'),
            uom_id=uuid4(),
        )
        line = await build_document_line(line_data, line_number=1)
        assert line.quantity == Decimal('5')
        assert line.expected_quantity == Decimal('5')
        assert line.done_quantity == Decimal('0.000')
        assert line.line_number == 1
        assert line.product_snapshot is None

    @pytest.mark.asyncio
    async def test_builds_line_with_product_snapshot(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        tpl = _make_template()
        line_data = _make_line_data(product_template_id=tpl.id)
        mock_core = MagicMock()
        mock_core.product_templates.get_async = AsyncMock(return_value=tpl)
        mock_core.uoms.validate_quantity_precision_async = AsyncMock()
        with patch('app.modules.warehouse.document_line_resolver.core_api', mock_core):
            line = await build_document_line(
                line_data, line_number=2, db=db, org_id=org_id
            )
        assert line.product_snapshot is not None
        assert line.product_snapshot['name'] == 'Test Product'
        assert line.line_number == 2

    @pytest.mark.asyncio
    async def test_falls_back_to_snapshot_uom(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        tpl = _make_template()
        tpl.uom_id = uuid4()
        line_data = _make_line_data(product_template_id=tpl.id, uom_id=None)
        mock_core = MagicMock()
        mock_core.product_templates.get_async = AsyncMock(return_value=tpl)
        mock_core.uoms.validate_quantity_precision_async = AsyncMock()
        with patch('app.modules.warehouse.document_line_resolver.core_api', mock_core):
            line = await build_document_line(
                line_data, line_number=1, db=db, org_id=org_id
            )
        assert line.uom_id == tpl.uom_id

    @pytest.mark.asyncio
    async def test_item_line_without_a_name_takes_the_items_name(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        item = MagicMock()
        item.name = 'Review approval item'
        item.uom_id = uuid4()
        line_data = _make_line_data(item_id=uuid4(), name=None, uom_id=uuid4())
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.uoms.validate_quantity_precision_async = AsyncMock()
        with patch('app.modules.warehouse.document_line_resolver.core_api', mock_core):
            line = await build_document_line(
                line_data, line_number=1, db=db, org_id=org_id
            )
        assert line.name == 'Review approval item'

    @pytest.mark.asyncio
    async def test_item_line_keeps_the_name_it_was_given(self) -> None:
        db = MagicMock()
        item = MagicMock()
        item.name = 'Item record name'
        item.uom_id = uuid4()
        line_data = _make_line_data(item_id=uuid4(), name='Typed name', uom_id=uuid4())
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.uoms.validate_quantity_precision_async = AsyncMock()
        with patch('app.modules.warehouse.document_line_resolver.core_api', mock_core):
            line = await build_document_line(
                line_data, line_number=1, db=db, org_id=uuid4()
            )
        assert line.name == 'Typed name'

    @pytest.mark.asyncio
    async def test_preserves_currency(self) -> None:
        line_data = _make_line_data()
        line = await build_document_line(line_data, line_number=1, currency='EUR')
        assert line.currency == 'EUR'
