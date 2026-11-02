from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.money import LineAmounts, line_amounts
from app.modules.purchase_orders._service_crud import update_purchase_order


@pytest.mark.unit
class TestUpdatePurchaseOrder:
    @pytest.fixture(autouse=True)
    def _no_journal(self) -> Iterator[None]:
        # The orders here are bare mocks; what the journal entry says is the
        # integration tests' business, not these header and guard cases.
        with (
            patch(
                'app.modules.purchase_orders._service_crud.edit_state',
                new=AsyncMock(return_value={}),
            ),
            patch(
                'app.modules.purchase_orders._service_crud.journal_order_act',
                new=AsyncMock(),
            ),
        ):
            yield

    @pytest.mark.asyncio
    async def test_raises_when_not_found(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        po_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        data = MagicMock()
        data.partner_id = None
        data.scheduled_date = None
        data.notes = None
        data.currency = None
        data.lines = None
        with pytest.raises(ValueError, match='not found'):
            await update_purchase_order(db, org_id, po_id, data, uuid4())

    @pytest.mark.asyncio
    async def test_raises_when_not_draft(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        po_id = uuid4()
        po = MagicMock()
        po.status = 'CONFIRMED'
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        data = MagicMock()
        data.partner_id = None
        data.scheduled_date = None
        data.notes = None
        data.currency = None
        data.lines = None
        with pytest.raises(ValueError, match='Only DRAFT'):
            await update_purchase_order(db, org_id, po_id, data, uuid4())

    @pytest.mark.asyncio
    async def test_raises_when_lines_have_received_qty(self) -> None:
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.delete = AsyncMock()
        org_id = uuid4()
        po_id = uuid4()
        po = MagicMock()
        po.status = 'DRAFT'
        line = MagicMock()
        line.quantity_received = Decimal('5')
        po.lines = [line]
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        data = MagicMock()
        data.partner_id = None
        data.scheduled_date = None
        data.notes = None
        data.currency = None
        data.lines = [MagicMock()]
        with pytest.raises(ValueError, match='Cannot update lines'):
            await update_purchase_order(db, org_id, po_id, data, uuid4())

    @pytest.mark.asyncio
    async def test_updates_header_fields(self) -> None:
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        org_id = uuid4()
        po_id = uuid4()
        po = MagicMock()
        po.status = 'DRAFT'
        po.lines = []
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        data = MagicMock()
        data.partner_id = uuid4()
        data.scheduled_date = datetime.now(UTC).date()
        data.notes = 'Updated notes'
        data.currency = 'EUR'
        data.lines = None
        with (
            patch('app.modules.purchase_orders._service_crud.core_api') as mock_core,
            patch(
                'app.modules.purchase_orders._service_crud.warehouse_api'
            ) as mock_docs,
        ):
            mock_core.partners.get_async = AsyncMock(return_value=MagicMock())
            mock_docs.renumber_for_date_async = AsyncMock(return_value='PO/2026/0001')
            result = await update_purchase_order(db, org_id, po_id, data, uuid4())
        assert result == po


@pytest.mark.unit
class TestComputeLineTotals:
    """Line totals via the shared ``line_amounts`` (the PO context builder's
    math — the PDF used to duplicate it in ``_compute_line_totals``)."""

    def _amounts(
        self,
        unit_price: Decimal | None,
        tax_rate: Decimal | None,
        qty: Decimal,
    ) -> LineAmounts:
        return line_amounts(qty, unit_price, tax_rate, places=None)

    def test_basic_calculation(self) -> None:
        amounts = self._amounts(Decimal('100.00'), Decimal('23'), Decimal('10'))
        assert amounts.net == Decimal('1000.00')
        assert amounts.tax == Decimal('230.00')
        assert amounts.gross == Decimal('1230.00')

    def test_zero_price(self) -> None:
        amounts = self._amounts(None, Decimal('23'), Decimal('10'))
        assert amounts.net == Decimal('0')
        assert amounts.tax == Decimal('0')
        assert amounts.gross == Decimal('0')

    def test_zero_tax_rate(self) -> None:
        amounts = self._amounts(Decimal('50.00'), None, Decimal('5'))
        assert amounts.net == Decimal('250.00')
        assert amounts.tax == Decimal('0')
        assert amounts.gross == Decimal('250.00')

    def test_fractional_values(self) -> None:
        amounts = self._amounts(Decimal('33.33'), Decimal('8'), Decimal('3'))
        assert amounts.net == Decimal('99.99')
        assert amounts.tax == Decimal('99.99') * Decimal('8') / Decimal('100')
        assert amounts.gross == amounts.net + amounts.tax
