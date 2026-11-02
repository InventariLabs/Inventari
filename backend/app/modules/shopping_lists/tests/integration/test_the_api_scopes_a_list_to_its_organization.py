"""The cross-module API must not take a caller's word for whose list it is.

``add_items_async`` and ``get_list_items_async`` were addressed by a bare
``list_id``. Whether that id belonged to the caller's organization was
decided by the caller — both of today's callers happen to check, so nothing
is broken right now, and that is precisely the shape a confused deputy has
before someone writes the third caller.

``add_items_async`` was worse than unchecked: when the list did not exist at
all it skipped the module gate and inserted the rows anyway, leaving items
pointing at nothing.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ShoppingListItemCreateDTO
from app.core.exceptions import NotFoundException
from app.models.organization import Organization
from app.models.user import User
from app.modules.shopping_lists.models import ShoppingList, ShoppingListItem
from app.modules.shopping_lists.shopping_lists_api import shopping_lists_api


@pytest.fixture
async def other_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Someone Else', enabled_modules=['core', 'shopping_lists'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def their_list(
    real_async_db_session: AsyncSession, other_org: Organization, async_test_user: User
) -> ShoppingList:
    shopping_list = ShoppingList(
        organization_id=other_org.id,
        created_by=async_test_user.id,
        name='Their List',
    )
    real_async_db_session.add(shopping_list)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(shopping_list)
    return shopping_list


@pytest.fixture
async def my_list(
    real_async_db_session: AsyncSession, async_test_user: User
) -> ShoppingList:
    shopping_list = ShoppingList(
        organization_id=_org_of(async_test_user),
        created_by=async_test_user.id,
        name='My List',
    )
    real_async_db_session.add(shopping_list)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(shopping_list)
    return shopping_list


def _one_item() -> list[ShoppingListItemCreateDTO]:
    return [ShoppingListItemCreateDTO(name='Flour', quantity=1)]


def _org_of(user: User) -> UUID:
    assert user.organization_id is not None
    return user.organization_id


@pytest.mark.integration
class TestAddItems:
    @pytest.mark.asyncio
    async def test_a_list_of_another_organization_is_refused(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        their_list: ShoppingList,
    ) -> None:
        with pytest.raises(NotFoundException):
            await shopping_lists_api.add_items_async(
                real_async_db_session,
                their_list.id,
                _one_item(),
                _org_of(async_test_user),
            )

        rows = await real_async_db_session.scalars(
            ShoppingListItem.__table__.select().where(
                ShoppingListItem.shopping_list_id == their_list.id
            )
        )
        assert list(rows) == []

    @pytest.mark.asyncio
    async def test_a_list_that_does_not_exist_is_refused(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        """It used to insert the rows anyway, pointing at nothing."""
        with pytest.raises(NotFoundException):
            await shopping_lists_api.add_items_async(
                real_async_db_session,
                uuid4(),
                _one_item(),
                _org_of(async_test_user),
            )

    @pytest.mark.asyncio
    async def test_my_own_list_still_takes_items(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        my_list: ShoppingList,
    ) -> None:
        added = await shopping_lists_api.add_items_async(
            real_async_db_session,
            my_list.id,
            _one_item(),
            _org_of(async_test_user),
        )

        assert [item.name for item in added] == ['Flour']


@pytest.mark.integration
class TestReadItems:
    @pytest.mark.asyncio
    async def test_a_list_of_another_organization_is_refused(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        their_list: ShoppingList,
    ) -> None:
        with pytest.raises(NotFoundException):
            await shopping_lists_api.get_list_items_async(
                real_async_db_session,
                their_list.id,
                _org_of(async_test_user),
            )

    @pytest.mark.asyncio
    async def test_my_own_list_reads_back(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        my_list: ShoppingList,
    ) -> None:
        await shopping_lists_api.add_items_async(
            real_async_db_session,
            my_list.id,
            _one_item(),
            _org_of(async_test_user),
        )

        items = await shopping_lists_api.get_list_items_async(
            real_async_db_session, my_list.id, _org_of(async_test_user)
        )

        assert [item.name for item in items] == ['Flour']
