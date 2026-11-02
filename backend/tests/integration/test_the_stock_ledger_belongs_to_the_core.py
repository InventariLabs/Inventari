"""The movement ledger answers to the organization, not to one module.

Every path that changes physical stock writes a ``StockMove``, and one of
them is Core's own: ``services/items/_stock_quant.py`` records a movement
whenever a record's quantity changes. The only way to read those rows back
was ``GET /api/v1/warehouse/stock/moves`` — a route the warehouse module
registers behind ``require_module('warehouse')``.

So an organization running a warehouse without that one module wrote to a
ledger it had no way to open. The ledger is Core's, and it answers from
Core: with rows when there are rows, with an empty list when there are none,
and never with a 404 that blames the caller for a module they did not ask
for.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _org_without_documents(db: AsyncSession, name: str) -> Organization:
    """An organization that keeps stock but never installed ``documents``."""
    org = Organization(name=name, enabled_modules=['core', 'items', 'locations'])
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def _shelf(db: AsyncSession, org: Organization, user: User) -> StorageLocation:
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        name='Aisle 1',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
    )
    db.add(location)
    await db.commit()
    await db.refresh(location)
    return location


async def _template(db: AsyncSession, org: Organization) -> ProductTemplate:
    template = ProductTemplate(name='Flour', organization_id=org.id)
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


async def _movement(
    db: AsyncSession,
    org: Organization,
    template: ProductTemplate,
    location: StorageLocation,
    quantity: str,
) -> StockMove:
    move = StockMove(
        organization_id=org.id,
        product_template_id=template.id,
        to_location_id=location.id,
        quantity=Decimal(quantity),
        reference_type='item',
    )
    db.add(move)
    await db.commit()
    await db.refresh(move)
    return move


@pytest.fixture
async def ledger_org(real_async_db_session: AsyncSession) -> Organization:
    return await _org_without_documents(real_async_db_session, 'Ledger Test Org')


@pytest.fixture
async def ledger_user(
    real_async_db_session: AsyncSession, ledger_org: Organization
) -> User:
    user = await ModuleTestHelper.create_user_async(
        real_async_db_session, ledger_org, email=f'ledger_{uuid4().hex[:8]}@test.com'
    )
    await real_async_db_session.commit()
    return user


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheStockLedgerBelongsToTheCore:
    async def test_an_organization_without_documents_can_read_its_ledger(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        ledger_org: Organization,
        ledger_user: User,
    ) -> None:
        db = real_async_db_session
        template = await _template(db, ledger_org)
        location = await _shelf(db, ledger_org, ledger_user)
        await _movement(db, ledger_org, template, location, '7.000')

        response = await real_async_client.get(
            '/api/v1/stock-moves', headers=_auth(ledger_user)
        )

        assert response.status_code == status.HTTP_200_OK
        rows = response.json()['items']
        assert len(rows) == 1
        assert rows[0]['product_template_id'] == str(template.id)
        assert Decimal(str(rows[0]['quantity'])) == Decimal('7.000')

    async def test_an_empty_ledger_is_an_empty_list_not_a_refusal(
        self,
        real_async_client: AsyncClient,
        ledger_user: User,
    ) -> None:
        """Nothing recorded yet is an answer, not an error."""
        response = await real_async_client.get(
            '/api/v1/stock-moves', headers=_auth(ledger_user)
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['items'] == []

    async def test_the_ledger_stops_at_the_organizations_edge(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        ledger_org: Organization,
        ledger_user: User,
    ) -> None:
        db = real_async_db_session
        stranger = await _org_without_documents(db, 'Someone Else')
        stranger_user = await ModuleTestHelper.create_user_async(
            db, stranger, email=f'stranger_{uuid4().hex[:8]}@test.com'
        )
        await db.commit()
        template = await _template(db, stranger)
        location = await _shelf(db, stranger, stranger_user)
        await _movement(db, stranger, template, location, '3.000')

        response = await real_async_client.get(
            '/api/v1/stock-moves', headers=_auth(ledger_user)
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['items'] == []

    async def test_a_caller_without_a_token_is_refused(
        self, real_async_client: AsyncClient
    ) -> None:
        response = await real_async_client.get('/api/v1/stock-moves')

        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )
