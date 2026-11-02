from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.announcement import Announcement
from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def ann_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Announcements Test Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'stats'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def ann_admin(real_async_db_session: AsyncSession, ann_org: Organization) -> User:
    user = User(
        email=f'ann_admin_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Ann Admin',
        organization_id=ann_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def ann_user(real_async_db_session: AsyncSession, ann_org: Organization) -> User:
    user = User(
        email=f'ann_user_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Ann User',
        organization_id=ann_org.id,
        role='user',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def ann_superuser(
    real_async_db_session: AsyncSession, ann_org: Organization
) -> User:
    """The installation owner — the only role that speaks to every tenant."""
    user = User(
        email=f'ann_super_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Ann Superuser',
        organization_id=ann_org.id,
        role='admin',
        is_active=True,
        is_superuser=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def other_org_user(real_async_db_session: AsyncSession) -> User:
    """A user of a different tenant on the same installation."""
    org = Organization(
        name='Other Announcements Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'stats'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)

    user = User(
        email=f'ann_other_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Ann Other',
        organization_id=org.id,
        role='user',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.mark.integration
@pytest.mark.asyncio
class TestAnnouncementsAPI:
    async def test_create_announcement_as_superuser(
        self, real_async_client, ann_superuser
    ):
        """The installation owner can create an announcement via JSON body."""
        response = await real_async_client.post(
            '/api/v1/announcements',
            headers=_auth(ann_superuser),
            json={
                'title': 'Maintenance',
                'content': 'System update tonight',
                'type': 'warning',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['title'] == 'Maintenance'
        assert data['type'] == 'warning'

    async def test_create_announcement_unauthorized(self, real_async_client, ann_user):
        """Regular user cannot create announcement."""
        response = await real_async_client.post(
            '/api/v1/announcements',
            headers=_auth(ann_user),
            json={'title': 'Hack', 'content': 'Hack content'},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_get_active_announcements(
        self, real_async_client, real_async_db_session, ann_user
    ):
        """Users can see active announcements."""
        ann1 = Announcement(
            title='Active One',
            content='Content',
            type='info',
            is_active=True,
            active_from=datetime.now(UTC) - timedelta(days=1),
        )
        ann2 = Announcement(
            title='Inactive One', content='Content', type='info', is_active=False
        )
        real_async_db_session.add_all([ann1, ann2])
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/announcements/active', headers=_auth(ann_user)
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        assert len(data) >= 1
        assert any(a['title'] == 'Active One' for a in data)
        assert not any(a['title'] == 'Inactive One' for a in data)

    async def test_org_admin_cannot_reach_another_organization(
        self, real_async_client, ann_admin, other_org_user
    ):
        """Announcements are installation-wide, so writing one is not an act an
        organisation admin gets to perform: the row has no tenant and every
        other organisation would read it. Admin of org A is refused, and org B
        sees nothing.
        """
        response = await real_async_client.post(
            '/api/v1/announcements',
            headers=_auth(ann_admin),
            json={
                'title': 'Cross-tenant leak',
                'content': 'Visible to strangers',
                'type': 'warning',
            },
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        response = await real_async_client.get(
            '/api/v1/announcements/active', headers=_auth(other_org_user)
        )
        assert response.status_code == status.HTTP_200_OK
        assert not any(
            a['title'] == 'Cross-tenant leak' for a in response.json()['items']
        )

    async def test_org_admin_cannot_list_or_delete(
        self, real_async_client, real_async_db_session, ann_admin
    ):
        """The full list and the delete are installation surfaces too."""
        announcement = Announcement(
            title='Installation notice',
            content='Content',
            type='info',
            is_active=True,
        )
        real_async_db_session.add(announcement)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(announcement)

        response = await real_async_client.get(
            '/api/v1/announcements', headers=_auth(ann_admin)
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        response = await real_async_client.delete(
            f'/api/v1/announcements/{announcement.id}', headers=_auth(ann_admin)
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_superuser_announcement_reaches_every_organization(
        self, real_async_client, ann_superuser, other_org_user
    ):
        """What the installation owner posts is meant to cross tenants — that is
        the whole point of the surface, and the reason writing it is theirs.
        """
        response = await real_async_client.post(
            '/api/v1/announcements',
            headers=_auth(ann_superuser),
            json={
                'title': 'Scheduled downtime',
                'content': 'Saturday 02:00 UTC',
                'type': 'downtime',
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        response = await real_async_client.get(
            '/api/v1/announcements/active', headers=_auth(other_org_user)
        )
        assert response.status_code == status.HTTP_200_OK
        assert any(a['title'] == 'Scheduled downtime' for a in response.json()['items'])
