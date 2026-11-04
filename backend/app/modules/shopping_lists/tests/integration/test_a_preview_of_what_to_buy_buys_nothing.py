"""Looking at what the app suggests must not change anything.

The dashboard's low-stock tile carries a button that opens "Review
suggestions". One click, before the reader had agreed to anything, sent:

    POST /shopping-lists
    GET  /shopping-lists?active_only=true
    POST /shopping-lists/{id}/suggestions/generate
    GET  /shopping-lists/{id}

The first of those created a shopping list. The modal it opened offered
Cancel, and Cancel did not undo it: the organization was left with an
empty active list it had never asked for, and a new section on the
dashboard advertising it.

Nothing about the suggestion itself needed that list. The generate route
adds no rows either — despite the name, it reads — and the list served
only to subtract what was already on it. So the read now has a door of
its own, and a list is created when somebody decides to buy something.

The same door answers the other half of the report: the button hangs on
the tile counting shortages and opened a modal of items that had
*expired*, because the suggestion engine returns every source it knows
unless it is asked otherwise. It can be asked now.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Item, ProductTemplate
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.modules.shopping_lists.models import ShoppingList
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token
from tests.integration._shelf import anchor_pending_records


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def buy_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Preview Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'shopping_lists'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def buy_user(real_async_db_session: AsyncSession, buy_org: Organization) -> User:
    user = User(
        email=f'buy_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('Password123'),
        full_name='Preview User',
        organization_id=buy_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def a_product_that_is_short(
    real_async_db_session: AsyncSession, buy_org: Organization, buy_user: User
) -> ProductTemplate:
    location = StorageLocation(
        organization_id=buy_org.id,
        created_by=buy_user.id,
        name='Pantry',
    )
    real_async_db_session.add(location)
    await real_async_db_session.flush()

    product = ProductTemplate(
        organization_id=buy_org.id,
        name=f'Salt {uuid.uuid4().hex[:6]}',
        min_quantity=10,
    )
    real_async_db_session.add(product)
    await real_async_db_session.flush()

    real_async_db_session.add(
        Item(
            organization_id=buy_org.id,
            storage_location_id=location.id,
            template_id=product.id,
            name=product.name,
            quantity=1,
        )
    )
    await real_async_db_session.run_sync(anchor_pending_records)
    await real_async_db_session.commit()
    return product


async def _list_count(db: AsyncSession, org_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count(ShoppingList.id)).where(
                ShoppingList.organization_id == org_id
            )
        )
    ) or 0


@pytest.mark.integration
class TestThePreviewLeavesNoTrace:
    async def test_it_answers_without_a_list_and_creates_none(
        self,
        real_async_client: Any,
        real_async_db_session: AsyncSession,
        buy_user: User,
        buy_org: Organization,
        a_product_that_is_short: ProductTemplate,
    ) -> None:
        before = await _list_count(real_async_db_session, buy_org.id)

        response = await real_async_client.get(
            '/api/v1/shopping-lists/suggestions', headers=_auth(buy_user)
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        names = [s['name'] for s in response.json()['suggestions']]
        assert a_product_that_is_short.name in names

        after = await _list_count(real_async_db_session, buy_org.id)
        assert after == before

    async def test_it_can_be_asked_for_shortages_alone(
        self,
        real_async_client: Any,
        buy_user: User,
        a_product_that_is_short: ProductTemplate,
    ) -> None:
        # The button lives on the tile that counts shortages, so it has to
        # be able to ask for shortages — not for everything the engine
        # knows, which is how a low-stock button came to show a screenful
        # of expired products.
        response = await real_async_client.get(
            '/api/v1/shopping-lists/suggestions',
            params={
                'include_low_stock': True,
                'include_expiring': False,
                'include_frequent': False,
            },
            headers=_auth(buy_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        sources = {s['source'] for s in response.json()['suggestions']}
        assert sources <= {'auto_low_stock'}, sources

    async def test_the_route_is_not_read_as_a_list_id(
        self,
        real_async_client: Any,
        buy_user: User,
    ) -> None:
        # `GET /{list_id}` stands on the same prefix; declared after it,
        # this path would be parsed as a malformed UUID and answered 422.
        response = await real_async_client.get(
            '/api/v1/shopping-lists/suggestions', headers=_auth(buy_user)
        )

        assert response.status_code != 422, response.text


@pytest.mark.integration
class TestAProposalNamesItsUnitForTheListRow:
    async def test_the_proposal_carries_the_unit_id_beside_its_symbol(
        self,
        real_async_client: Any,
        real_async_db_session: AsyncSession,
        buy_user: User,
        a_product_that_is_short: ProductTemplate,
    ) -> None:
        # The review sheet printed "pcs" from the symbol, but a row added from
        # it could only be built from what the proposal carried: no unit id,
        # so the line landed on the list with "—" where the sheet said "pcs".
        unit = await real_async_db_session.scalar(
            select(Uom).where(Uom.symbol == 'pcs')
        )
        assert unit is not None
        a_product_that_is_short.uom_id = unit.id
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/shopping-lists/suggestions', headers=_auth(buy_user)
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        proposal = next(
            s
            for s in response.json()['suggestions']
            if s['name'] == a_product_that_is_short.name
        )
        assert proposal['uom_symbol'] == 'pcs'
        assert proposal['uom_id'] == str(unit.id)
