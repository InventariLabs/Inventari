"""A completed list is frozen, so nothing may pick it as the place for a new item.

The list's own endpoint answers 409 to an item added to a completed list, but
two other roads went around it. ``add_items_async`` — the cross-module door the
recipe card, the meal plan and a production run write through — never looked at
the list's status, so a line landed on a list the reader had already finished.
And ``GET /shopping-lists?active_only=true``, which the recipe card and the scan
add read to find "the newest list", only drops archived lists, so a completed
one came back first whenever it was the newest.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.contracts import ShoppingListItemCreateDTO
from app.core.exceptions import ServiceRejectionError
from app.models.user import User
from app.modules.shopping_lists.models import ShoppingList, ShoppingListItem
from app.modules.shopping_lists.shopping_lists_api import shopping_lists_api


def _org_of(user: User) -> UUID:
    assert user.organization_id is not None
    return user.organization_id


async def a_list(db: AsyncSession, user: User, state: str) -> ShoppingList:
    assert user.organization_id is not None
    shopping_list = ShoppingList(
        organization_id=user.organization_id,
        created_by=user.id,
        name=f'{state} list',
        status=state,
    )
    db.add(shopping_list)
    await db.flush()
    await db.refresh(shopping_list)
    return shopping_list


@pytest.mark.integration
class TestTheFacadeRefusesAFrozenList:
    @pytest.mark.asyncio
    @pytest.mark.parametrize('state', ['completed', 'archived'])
    async def test_a_frozen_list_is_refused_and_stays_empty(
        self, real_async_db_session: AsyncSession, async_test_user: User, state: str
    ) -> None:
        shopping_list = await a_list(real_async_db_session, async_test_user, state)

        with pytest.raises(ServiceRejectionError) as refused:
            await shopping_lists_api.add_items_async(
                real_async_db_session,
                shopping_list.id,
                [ShoppingListItemCreateDTO(name='Flour', quantity=1)],
                _org_of(async_test_user),
            )

        assert refused.value.key == 'shopping_list_not_writable'
        rows = await real_async_db_session.scalars(
            ShoppingListItem.__table__.select().where(
                ShoppingListItem.shopping_list_id == shopping_list.id
            )
        )
        assert list(rows) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize('state', ['completed', 'archived'])
    async def test_a_frozen_lists_line_is_not_raised_by_a_top_up(
        self, real_async_db_session: AsyncSession, async_test_user: User, state: str
    ) -> None:
        shopping_list = await a_list(real_async_db_session, async_test_user, 'active')
        org = _org_of(async_test_user)
        need = ShoppingListItemCreateDTO(
            name='Coconut Milk', quantity=Decimal('100'), source='meal_plan'
        )
        [line] = await shopping_lists_api.add_items_async(
            real_async_db_session, shopping_list.id, [need], org
        )
        shopping_list.status = state
        await real_async_db_session.flush()

        with pytest.raises(ServiceRejectionError) as refused:
            await shopping_lists_api.top_up_async(
                real_async_db_session,
                shopping_list.id,
                need.model_copy(update={'quantity': Decimal('400')}),
                [line],
                org,
            )

        assert refused.value.key == 'shopping_list_not_writable'
        stored = await real_async_db_session.scalar(
            select(ShoppingListItem.quantity).where(ShoppingListItem.id == line.id)
        )
        assert stored == Decimal('100')

    @pytest.mark.asyncio
    async def test_an_active_list_still_takes_items(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        shopping_list = await a_list(real_async_db_session, async_test_user, 'active')

        added = await shopping_lists_api.add_items_async(
            real_async_db_session,
            shopping_list.id,
            [ShoppingListItemCreateDTO(name='Flour', quantity=1)],
            _org_of(async_test_user),
        )

        assert [line.name for line in added] == ['Flour']


@pytest.mark.integration
class TestTheListsCanBeAskedByStatus:
    def test_status_active_leaves_out_a_completed_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        completed = ShoppingList(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='Last week done',
            status='completed',
        )
        db_session.add(completed)
        db_session.commit()

        everything = client.get('/api/v1/shopping-lists', headers=auth_headers)
        open_only = client.get(
            '/api/v1/shopping-lists?status=active', headers=auth_headers
        )

        assert everything.status_code == status.HTTP_200_OK
        assert open_only.status_code == status.HTTP_200_OK
        wanted = str(completed.id)
        # Still readable in the plain listing, but not offered as a target.
        assert wanted in {row['id'] for row in everything.json()['items']}
        assert wanted not in {row['id'] for row in open_only.json()['items']}

    def test_an_unknown_status_is_refused(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            '/api/v1/shopping-lists?status=nonsense', headers=auth_headers
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
