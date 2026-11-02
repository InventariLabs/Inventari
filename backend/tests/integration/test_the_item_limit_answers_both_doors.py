"""The organization's item limit answers both doors into the warehouse.

An organization at its configured item limit was refused when the product
arrived by scan and waved through when the same product was typed into the
form: the quota gate lived in the scan service alone. Both creations answer
to one gate now, with the same refusal — and neither of them refuses
anything below the limit.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.label_pool import LabelPool
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration

_LIMIT_MESSAGE = 'Item limit reached for this organization. Upgrade to Inventari Cloud.'


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def quota_shelf(
    real_async_db_session: AsyncSession, async_test_user: User
) -> StorageLocation:
    shelf = StorageLocation(
        organization_id=async_test_user.organization_id,
        created_by=async_test_user.id,
        name='Quota Shelf',
    )
    real_async_db_session.add(shelf)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(shelf)
    return shelf


@pytest.fixture
async def quota_label(
    real_async_db_session: AsyncSession, async_test_user: User
) -> LabelPool:
    label = LabelPool(
        short_code=f'STM-Q{uuid.uuid4().hex[:5].upper()}',
        organization_id=async_test_user.organization_id,
        created_by=async_test_user.id,
        is_assigned=False,
    )
    real_async_db_session.add(label)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(label)
    return label


@pytest.fixture
async def quota_user(
    real_async_db_session: AsyncSession, async_test_user: User
) -> User:
    """The org and its user, committed — the HTTP client uses its own session."""
    await real_async_db_session.commit()
    return async_test_user


@pytest.fixture
async def quota_denied(put_on_item_limit, async_test_household) -> None:
    """The organization stands at its limit — set through the registry the
    gate reads, not by patching the gate itself."""
    put_on_item_limit(async_test_household.id)


@pytest.mark.asyncio
class TestTheItemLimitAnswersBothDoors:
    async def test_the_form_refuses_a_record_over_the_limit(
        self, real_async_client, quota_user, quota_shelf, quota_denied
    ):
        """POST /api/v1/items was the door the gate was missing from: the
        refusal travelled as an unhandled PermissionError, which a reader
        met as a 500."""
        response = await real_async_client.post(
            '/api/v1/items',
            headers=_auth(quota_user),
            json={
                'name': 'One Too Many',
                'location_id': str(quota_shelf.id),
                'quantity': 1,
            },
        )

        assert response.status_code == 403, response.text
        detail = response.json()['detail']
        assert detail['message'] == _LIMIT_MESSAGE
        assert detail['code'] == 'FORBIDDEN'

    async def test_the_scan_refuses_a_record_over_the_limit(
        self, real_async_client, quota_user, quota_shelf, quota_label, quota_denied
    ):
        response = await real_async_client.post(
            f'/api/v1/labels/scan/{quota_label.short_code}/assign',
            headers=_auth(quota_user),
            json={
                'name': 'One Too Many',
                'location_id': str(quota_shelf.id),
                'quantity': 1,
            },
        )

        assert response.status_code == 403, response.text
        detail = response.json()['detail']
        assert detail['message'] == _LIMIT_MESSAGE
        assert detail['code'] == 'FORBIDDEN'

    async def test_the_refusal_speaks_the_readers_language(
        self, real_async_client, quota_user, quota_shelf, quota_denied
    ):
        response = await real_async_client.post(
            '/api/v1/items',
            headers={**_auth(quota_user), 'Accept-Language': 'pl'},
            json={
                'name': 'One Too Many',
                'location_id': str(quota_shelf.id),
                'quantity': 1,
            },
        )

        assert response.status_code == 403, response.text
        assert response.json()['detail']['message'] == (
            'Ta organizacja osiągnęła limit produktów. Przejdź na Inventari Cloud.'
        )

    async def test_below_the_limit_neither_door_is_blocked(
        self, real_async_client, quota_user, quota_shelf, quota_label
    ):
        form = await real_async_client.post(
            '/api/v1/items',
            headers=_auth(quota_user),
            json={
                'name': 'Below The Limit',
                'location_id': str(quota_shelf.id),
                'quantity': 1,
            },
        )
        assert form.status_code == 201, form.text

        scan = await real_async_client.post(
            f'/api/v1/labels/scan/{quota_label.short_code}/assign',
            headers=_auth(quota_user),
            json={
                'name': 'Below The Limit By Scan',
                'location_id': str(quota_shelf.id),
                'quantity': 1,
            },
        )
        assert scan.status_code == 200, scan.text
