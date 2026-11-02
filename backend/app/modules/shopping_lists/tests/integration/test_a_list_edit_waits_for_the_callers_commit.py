"""Editing a shopping list is one unit of work with whatever the caller does next.

The service used to commit inside the edit, so a request that failed after
it (a serializer, a later write) had already renamed the list for good. The
caller owns the commit now: a rollback after the edit leaves the list as it
was.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.modules.shopping_lists.models import ShoppingList
from app.modules.shopping_lists.schemas import ShoppingListUpdate
from app.modules.shopping_lists.shopping_list_service import (
    update_shopping_list_fields,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_rollback_after_the_edit_leaves_the_list_as_it_was(
    real_async_db_session: AsyncSession,
) -> None:
    org = Organization(
        name=f'List Edit Org {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'shopping_lists'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    user = User(
        email=f'list_edit_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password='x',
        full_name='List Edit User',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    shopping_list = ShoppingList(
        organization_id=org.id, created_by=user.id, name='Before'
    )
    real_async_db_session.add(shopping_list)
    await real_async_db_session.commit()
    list_id = shopping_list.id

    await update_shopping_list_fields(
        real_async_db_session, shopping_list, ShoppingListUpdate(name='After')
    )
    await real_async_db_session.rollback()

    name = await real_async_db_session.scalar(
        select(ShoppingList.name).where(ShoppingList.id == list_id)
    )
    assert name == 'Before'
