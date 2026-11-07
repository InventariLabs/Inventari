from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.purchase_orders._service_workflow import (
    cancel_purchase_order,
    confirm_purchase_order,
)

_KEEP = object()


def _make_po(
    *,
    status: str = 'DRAFT',
    po_id: Any = None,
    number: str = 'PO/2026/0001',
    partner_id: Any = _KEEP,
    lines: list[Any] | None = None,
) -> MagicMock:
    po = MagicMock()
    po.id = po_id or uuid4()
    po.status = status
    po.number = number
    # Confirming needs a supplier, so one is the default here; the
    # test for the missing-supplier refusal passes None explicitly.
    po.partner_id = uuid4() if partner_id is _KEEP else partner_id
    po.confirmed_by = None
    po.confirmed_at = None
    po.cancelled_by = None
    po.cancelled_at = None
    po.lines = lines or []
    return po


def _make_partner(
    *, is_active: bool = True, partner_type: str = 'SUPPLIER', name: str = 'Acme'
) -> MagicMock:
    partner = MagicMock()
    partner.is_active = is_active
    partner.type = partner_type
    partner.name = name
    return partner


@pytest.mark.unit
class TestConfirmPurchaseOrder:
    @pytest.mark.asyncio
    async def test_raises_when_not_found(self) -> None:
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match='not found'):
            await confirm_purchase_order(db, uuid4(), uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_raises_when_not_draft(self) -> None:
        db = MagicMock()
        po = _make_po(status='CONFIRMED')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match='cannot be confirmed'):
            await confirm_purchase_order(db, uuid4(), po.id, uuid4())

    @pytest.mark.asyncio
    async def test_confirms_draft_po(self) -> None:
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        user_id = uuid4()
        po = _make_po(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with (
            patch(
                'app.modules.purchase_orders._service_workflow.get_po_settings',
                AsyncMock(return_value=None),
            ),
            patch(
                'app.modules.purchase_orders._service_workflow.core_api'
            ) as mock_core,
        ):
            mock_core.partners.get_async = AsyncMock(return_value=None)
            mock_core.audit_log.log_action_async = AsyncMock()
            mock_core.events.emit_transactional_async = AsyncMock()
            result = await confirm_purchase_order(db, uuid4(), po.id, user_id)
        assert result.status == 'CONFIRMED'
        assert result.confirmed_by == user_id

    @pytest.mark.asyncio
    async def test_writes_the_confirmed_event_to_the_outbox(self) -> None:
        """The event rides the confirm's own transaction, through the outbox."""
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        po = _make_po(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with (
            patch(
                'app.modules.purchase_orders._service_workflow.get_po_settings',
                AsyncMock(return_value=None),
            ),
            patch(
                'app.modules.purchase_orders._service_workflow.core_api'
            ) as mock_core,
        ):
            mock_core.partners.get_async = AsyncMock(return_value=None)
            mock_core.audit_log.log_action_async = AsyncMock()
            mock_core.events.emit_transactional_async = AsyncMock()
            await confirm_purchase_order(db, uuid4(), po.id, uuid4())
        mock_core.events.emit_transactional_async.assert_awaited_once()
        args = mock_core.events.emit_transactional_async.await_args.args
        assert args[0] is db
        assert args[1] == 'purchase_order.confirmed'
        assert args[2].po_id == str(po.id)

    @pytest.mark.asyncio
    async def test_a_failed_outbox_write_aborts_the_confirm(self) -> None:
        """An event that cannot be recorded is not swallowed: the caller's
        transaction rolls back with it, so no confirmed PO goes unannounced."""
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        po = _make_po(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with (
            patch(
                'app.modules.purchase_orders._service_workflow.get_po_settings',
                AsyncMock(return_value=None),
            ),
            patch(
                'app.modules.purchase_orders._service_workflow.core_api'
            ) as mock_core,
        ):
            mock_core.partners.get_async = AsyncMock(return_value=None)
            mock_core.audit_log.log_action_async = AsyncMock()
            mock_core.events.emit_transactional_async = AsyncMock(
                side_effect=RuntimeError('outbox down')
            )
            with pytest.raises(RuntimeError, match='outbox down'):
                await confirm_purchase_order(db, uuid4(), po.id, uuid4())


@pytest.mark.unit
class TestConfirmPurchaseOrderPartnerValidation:
    """confirm must validate partner is active and is a supplier type."""

    @pytest.mark.asyncio
    async def test_rejects_inactive_partner(self) -> None:
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        partner_id = uuid4()
        po = _make_po(status='DRAFT', partner_id=partner_id)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        partner = _make_partner(is_active=False)
        with (
            patch(
                'app.modules.purchase_orders._service_workflow.core_api'
            ) as mock_core,
        ):
            mock_core.partners.get_async = AsyncMock(return_value=partner)
            with pytest.raises(ValueError, match='inactive'):
                await confirm_purchase_order(db, uuid4(), po.id, uuid4())

    @pytest.mark.asyncio
    async def test_rejects_non_supplier_type(self) -> None:
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        partner_id = uuid4()
        po = _make_po(status='DRAFT', partner_id=partner_id)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        partner = _make_partner(partner_type='CUSTOMER')
        with (
            patch(
                'app.modules.purchase_orders._service_workflow.core_api'
            ) as mock_core,
        ):
            mock_core.partners.get_async = AsyncMock(return_value=partner)
            with pytest.raises(ValueError, match='not a supplier') as refused:
                await confirm_purchase_order(db, uuid4(), po.id, uuid4())
        # The reader's word for the type, not the stored value.
        assert 'type "Customer"' in str(refused.value)

    @pytest.mark.asyncio
    async def test_allows_both_type(self) -> None:
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        partner_id = uuid4()
        po = _make_po(status='DRAFT', partner_id=partner_id)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        partner = _make_partner(partner_type='BOTH')
        with (
            patch(
                'app.modules.purchase_orders._service_workflow.core_api'
            ) as mock_core,
            patch(
                'app.modules.purchase_orders._service_workflow.get_po_settings',
                AsyncMock(return_value=None),
            ),
        ):
            mock_core.partners.get_async = AsyncMock(return_value=partner)
            mock_core.audit_log.log_action_async = AsyncMock()
            mock_core.events.emit_transactional_async = AsyncMock()
            result = await confirm_purchase_order(db, uuid4(), po.id, uuid4())
        assert result.status == 'CONFIRMED'
        # The entry names the supplier beside the id: the row was read a few
        # lines up to check it, and a journal read months later has no way
        # back to the id. `Acme` is what `_make_partner` calls it.
        _, kwargs = mock_core.audit_log.log_action_async.call_args
        assert kwargs['snapshot']['partner_id'] == str(partner_id)
        assert kwargs['snapshot']['partner_name'] == 'Acme'

    @pytest.mark.asyncio
    async def test_refuses_when_no_partner(self) -> None:
        """A PO without a supplier cannot be confirmed at all."""
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        po = _make_po(status='DRAFT', partner_id=None)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with (
            patch(
                'app.modules.purchase_orders._service_workflow.core_api'
            ) as mock_core,
            patch(
                'app.modules.purchase_orders._service_workflow.get_po_settings',
                AsyncMock(return_value=None),
            ),
        ):
            mock_core.partners.get_async = AsyncMock()
            mock_core.audit_log.log_action_async = AsyncMock()
            with pytest.raises(ValueError, match='supplier'):
                await confirm_purchase_order(db, uuid4(), po.id, uuid4())
        # The refusal happens before any partner lookup.
        mock_core.partners.get_async.assert_not_awaited()
        assert po.status == 'DRAFT'


@pytest.mark.unit
class TestCancelPurchaseOrder:
    @pytest.mark.asyncio
    async def test_raises_when_not_found(self) -> None:
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match='not found'):
            await cancel_purchase_order(db, uuid4(), uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_raises_when_already_cancelled(self) -> None:
        db = MagicMock()
        po = _make_po(status='CANCELLED')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match='already cancelled'):
            await cancel_purchase_order(db, uuid4(), po.id, uuid4())

    @pytest.mark.asyncio
    async def test_raises_when_completed(self) -> None:
        db = MagicMock()
        po = _make_po(status='COMPLETED')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match='Cannot cancel a completed'):
            await cancel_purchase_order(db, uuid4(), po.id, uuid4())

    @pytest.mark.asyncio
    async def test_cancels_draft(self) -> None:
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        user_id = uuid4()
        po = _make_po(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with patch(
            'app.modules.purchase_orders._service_workflow.core_api.events.emit_transactional_async',
            AsyncMock(),
        ):
            result = await cancel_purchase_order(db, uuid4(), po.id, user_id)
        assert result.status == 'CANCELLED'
        assert result.cancelled_by == user_id

    @pytest.mark.asyncio
    async def test_cancels_confirmed(self) -> None:
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        po = _make_po(status='CONFIRMED')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with patch(
            'app.modules.purchase_orders._service_workflow.core_api.events.emit_transactional_async',
            AsyncMock(),
        ):
            result = await cancel_purchase_order(db, uuid4(), po.id, uuid4())
        assert result.status == 'CANCELLED'
