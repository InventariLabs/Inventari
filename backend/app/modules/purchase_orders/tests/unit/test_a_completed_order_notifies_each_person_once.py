"""One completed order, one notice per person.

The administrators are told that the order is complete, and the person who
raised it is told that theirs is. Someone who is both used to get both.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.modules.purchase_orders import _service_po_completion as completion
from app.modules.purchase_orders.models import PurchaseOrder

_NOTIFICATIONS = (
    'app.modules.purchase_orders._service_po_completion.core_api.notifications'
)
_EVENTS = 'app.modules.purchase_orders._service_po_completion.core_api.events'


def _order(created_by: UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), number='PO/2026/003', created_by=created_by)


async def _complete(order: SimpleNamespace, admins: list[UUID]) -> MagicMock:
    with (
        patch(_NOTIFICATIONS) as notifications,
        patch(_EVENTS) as events,
    ):
        events.emit_transactional_async = AsyncMock()
        notifications.localize = MagicMock(return_value='text')
        notifications.notify_org_admins_async = AsyncMock(
            return_value=[SimpleNamespace(user_id=a) for a in admins]
        )
        notifications.create_async = AsyncMock(
            return_value=SimpleNamespace(user_id=order.created_by)
        )
        notifications.publish_async = AsyncMock()
        await completion._emit_po_completed(
            MagicMock(), uuid4(), cast(PurchaseOrder, order)
        )
    return notifications


@pytest.mark.asyncio
async def test_a_creator_who_administers_is_told_once() -> None:
    creator = uuid4()
    notifications = await _complete(_order(creator), admins=[creator, uuid4()])

    notifications.create_async.assert_not_called()
    published = notifications.publish_async.call_args.args[1]
    assert [n.user_id for n in published].count(creator) == 1


@pytest.mark.asyncio
async def test_a_creator_who_is_not_an_administrator_is_told_too() -> None:
    creator = uuid4()
    notifications = await _complete(_order(creator), admins=[uuid4()])

    notifications.create_async.assert_awaited_once()
    published = notifications.publish_async.call_args.args[1]
    assert creator in [n.user_id for n in published]
