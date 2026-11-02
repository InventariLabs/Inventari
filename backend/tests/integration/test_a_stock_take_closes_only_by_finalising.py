"""A count has one way out, and it is not the status field.

Finalising a stock take is the step that does the work: it re-reads the row
under a lock, refuses to close while rows are still uncounted, checks the
inventory period, and writes every counted difference back into stock. The
status endpoint next to it did none of that — it took ``COMPLETED`` off a
table of allowed transitions and set the field. Same authority, same
organisation, one round trip, and the count was closed with rows nobody had
counted and not a single adjustment posted.

That is not a hole in tenancy: whoever can call it may legitimately close
the count. It is a second door into a room that was meant to have one, and
the tests below pin the door shut. Cancelling stays where it was — it is the
one status change that genuinely is just a status change, and the only thing
the interface uses this endpoint for.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token
from tests.integration._shelf import put_on_shelf


class _Counting:
    def __init__(self) -> None:
        self.headers: dict[str, str]
        self.stock_take_id: str


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def counting(
    real_async_db_session: AsyncSession, real_async_client: AsyncClient
) -> _Counting:
    """A shelf with something on it and a count under way over it."""
    db = real_async_db_session
    fixture = _Counting()

    org = Organization(
        name=f'Counting {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'stock_takes'],
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)

    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'count_{uuid4().hex[:8]}@test.com', role='admin'
    )
    await db.commit()
    fixture.headers = _auth(user)

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
    product = ProductTemplate(name='Rye flour', organization_id=org.id)
    db.add_all([location, product])
    await db.flush()
    await put_on_shelf(db, user, product, location.id, 100)
    await db.commit()

    created = await real_async_client.post(
        '/api/v1/stock-takes',
        headers=fixture.headers,
        json={'name': 'Monday count', 'location_id': str(location.id)},
    )
    assert created.status_code == 201, created.text
    assert created.json()['status'].lower() == 'in_progress'
    fixture.stock_take_id = created.json()['id']
    return fixture


@pytest.mark.integration
@pytest.mark.async_db
class TestTheStatusEndpointDoesNotClose:
    async def test_patching_the_status_to_completed_is_refused(
        self, real_async_client: AsyncClient, counting: _Counting
    ):
        response = await real_async_client.patch(
            f'/api/v1/stock-takes/{counting.stock_take_id}/status',
            headers=counting.headers,
            json={'status': 'completed'},
        )
        assert response.status_code == 400, response.text

    async def test_the_refusal_says_where_to_go_instead(
        self, real_async_client: AsyncClient, counting: _Counting
    ):
        response = await real_async_client.patch(
            f'/api/v1/stock-takes/{counting.stock_take_id}/status',
            headers=counting.headers,
            json={'status': 'completed'},
        )
        message = response.json()['detail']['message']
        assert 'complete' in message.lower(), message

    async def test_the_count_is_still_open_afterwards(
        self, real_async_client: AsyncClient, counting: _Counting
    ):
        await real_async_client.patch(
            f'/api/v1/stock-takes/{counting.stock_take_id}/status',
            headers=counting.headers,
            json={'status': 'completed'},
        )
        after = await real_async_client.get(
            f'/api/v1/stock-takes/{counting.stock_take_id}',
            headers=counting.headers,
        )
        assert after.status_code == 200
        assert after.json()['status'].lower() == 'in_progress'

    async def test_counting_everything_first_does_not_open_the_door(
        self, real_async_client: AsyncClient, counting: _Counting
    ):
        """The rule is one door, not a second completeness gate.

        A count with nothing left uncounted still has adjustments to post,
        and the status endpoint posts none — so it is refused just the same.
        """
        items = await real_async_client.get(
            f'/api/v1/stock-takes/{counting.stock_take_id}/items',
            headers=counting.headers,
        )
        assert items.status_code == 200
        rows = items.json()['items']
        assert rows, 'the fixture is meant to produce something to count'
        for row in rows:
            counted = await real_async_client.patch(
                f'/api/v1/stock-takes/{counting.stock_take_id}/items/{row["id"]}/count',
                headers=counting.headers,
                json={'counted_quantity': 100},
            )
            assert counted.status_code == 200, counted.text

        response = await real_async_client.patch(
            f'/api/v1/stock-takes/{counting.stock_take_id}/status',
            headers=counting.headers,
            json={'status': 'completed'},
        )
        assert response.status_code == 400, response.text


@pytest.mark.integration
@pytest.mark.async_db
class TestWhatTheStatusEndpointStillDoes:
    async def test_cancelling_goes_through_the_same_patch(
        self, real_async_client: AsyncClient, counting: _Counting
    ):
        """The one thing the interface uses this endpoint for."""
        response = await real_async_client.patch(
            f'/api/v1/stock-takes/{counting.stock_take_id}/status',
            headers=counting.headers,
            json={'status': 'cancelled'},
        )
        assert response.status_code == 200, response.text
        assert response.json()['status'].lower() == 'cancelled'

    async def test_finalising_still_closes_the_count(
        self, real_async_client: AsyncClient, counting: _Counting
    ):
        """The door that is left, exercised end to end."""
        items = await real_async_client.get(
            f'/api/v1/stock-takes/{counting.stock_take_id}/items',
            headers=counting.headers,
        )
        for row in items.json()['items']:
            await real_async_client.patch(
                f'/api/v1/stock-takes/{counting.stock_take_id}/items/{row["id"]}/count',
                headers=counting.headers,
                json={'counted_quantity': 100},
            )

        response = await real_async_client.post(
            f'/api/v1/stock-takes/{counting.stock_take_id}/complete',
            headers=counting.headers,
            json={'apply_adjustments': True},
        )
        assert response.status_code == 200, response.text
        assert response.json()['status'].lower() == 'completed'
