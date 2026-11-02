"""A QR read by the app's own scanner resolves whichever address it carries.

Labels print ``{base}/s/{code}`` now; the ones already stuck on shelves
carry ``{base}/scan?code={code}``. The in-app scanner sends whatever the
camera read, percent-encoded as one path segment the way the frontend's
``labelsApi.scan`` does, so both shapes have to come back as the same label.
"""

from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token

BASE = 'https://inventari12.warehouse-north.example-co.example.org'


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def scan_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Scan Address Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'printing'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def scan_user(
    real_async_db_session: AsyncSession, scan_org: Organization
) -> User:
    user = User(
        email=f'scan_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('Password123'),
        full_name='Scan Address User',
        organization_id=scan_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.mark.integration
class TestAPrintedAddressScans:
    async def _generated_code(self, client, user: User) -> str:
        generated = await client.post(
            '/api/v1/labels/pool/generate',
            json={'count': 1, 'prefix': 'STM'},
            headers=_auth(user),
        )
        assert generated.status_code == status.HTTP_201_CREATED
        return str(generated.json()[0]['short_code'])

    @pytest.mark.parametrize(
        'address',
        [
            # Spelled out rather than built by scan_url, so the case keeps
            # testing the short shape whatever scan_url prints.
            lambda code: f'{BASE}/s/{code}',
            lambda code: f'{BASE}/scan?code={code}',
        ],
        ids=['short-address', 'address-printed-before-it'],
    )
    async def test_the_scanned_address_resolves_to_its_label(
        self, real_async_client, scan_user, scan_org, address
    ) -> None:
        code = await self._generated_code(real_async_client, scan_user)

        scanned = await real_async_client.get(
            f'/api/v1/labels/scan/{quote(address(code), safe="")}',
            headers=_auth(scan_user),
        )

        assert scanned.status_code == status.HTTP_200_OK, scanned.text
        assert scanned.json()['label_code'] == code
