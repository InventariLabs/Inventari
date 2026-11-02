"""PO approval transitions are service functions: no HTTP client needed."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ConflictException
from app.modules.purchase_orders import _service_approval as svc

_APPROVALS = 'app.modules.purchase_orders._service_approval.approvals_api'
_EMIT = 'app.modules.purchase_orders._service_approval.core_api.events.emit_transactional_async'


def _po(status: str) -> MagicMock:
    po = MagicMock()
    po.id = uuid4()
    po.status = status
    po.number = 'PO/2026/0001'
    return po


def _db() -> MagicMock:
    db = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.mark.unit
class TestRequestApproval:
    @pytest.mark.asyncio
    async def test_parks_a_draft_order(self) -> None:
        po = _po('DRAFT')
        with patch(_APPROVALS) as api:
            api.request_approval = AsyncMock(return_value='request')
            result = await svc.request_purchase_order_approval(
                _db(), uuid4(), po, uuid4()
            )
        assert result == 'request'
        assert po.status == 'PENDING_APPROVAL'

    @pytest.mark.asyncio
    async def test_refuses_a_confirmed_order(self) -> None:
        po = _po('CONFIRMED')
        with pytest.raises(ConflictException):
            await svc.request_purchase_order_approval(_db(), uuid4(), po, uuid4())
        assert po.status == 'CONFIRMED'


@pytest.mark.unit
class TestApprove:
    @pytest.mark.asyncio
    async def test_final_stage_confirms_and_records_the_event(self) -> None:
        po = _po('PENDING_APPROVAL')
        with (
            patch(_APPROVALS) as api,
            patch.object(svc, '_confirm_po_after_approval', AsyncMock()) as confirm,
            patch(_EMIT, AsyncMock()) as emit,
        ):
            api.find_active_request = AsyncMock(return_value=SimpleNamespace(id=1))
            api.approve_stage = AsyncMock(
                return_value=SimpleNamespace(status='APPROVED')
            )
            await svc.approve_purchase_order(_db(), uuid4(), po, uuid4())
        confirm.assert_awaited_once()
        emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_intermediate_stage_leaves_the_order_parked(self) -> None:
        po = _po('PENDING_APPROVAL')
        with (
            patch(_APPROVALS) as api,
            patch.object(svc, '_confirm_po_after_approval', AsyncMock()) as confirm,
            patch(_EMIT, AsyncMock()) as emit,
        ):
            api.find_active_request = AsyncMock(return_value=SimpleNamespace(id=1))
            api.approve_stage = AsyncMock(
                return_value=SimpleNamespace(status='IN_PROGRESS')
            )
            await svc.approve_purchase_order(_db(), uuid4(), po, uuid4())
        confirm.assert_not_awaited()
        emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refuses_an_order_not_awaiting_approval(self) -> None:
        with pytest.raises(ConflictException):
            await svc.approve_purchase_order(_db(), uuid4(), _po('DRAFT'), uuid4())


@pytest.mark.unit
class TestReject:
    @pytest.mark.asyncio
    async def test_returns_the_order_to_draft_and_notifies(self) -> None:
        po = _po('PENDING_APPROVAL')
        with (
            patch(_APPROVALS) as api,
            patch.object(svc, 'core_api') as core,
        ):
            api.find_active_request = AsyncMock(
                return_value=SimpleNamespace(id=1, created_by=uuid4())
            )
            api.reject_request = AsyncMock(return_value='rejected')
            core.notifications.create_async = AsyncMock()
            core.notifications.publish_async = AsyncMock()
            result = await svc.reject_purchase_order(
                _db(), uuid4(), po, uuid4(), 'too dear'
            )
        assert result == 'rejected'
        assert po.status == 'DRAFT'
        core.notifications.publish_async.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_without_an_open_request_is_a_conflict(self) -> None:
        po = _po('PENDING_APPROVAL')
        with patch(_APPROVALS) as api:
            api.find_active_request = AsyncMock(return_value=None)
            with pytest.raises(ConflictException):
                await svc.reject_purchase_order(_db(), uuid4(), po, uuid4())
        assert po.status == 'PENDING_APPROVAL'
