"""A request for access reaches the people who can decide it, and only them.

A request for an account is not addressed to any organization: approving it
opens an account on the instance. So the list, the approval and the refusal
are the superuser's (``get_superuser``) — while the bell rang for every user
with ``role == 'admin'``, in every organization. An organization's own
administrator was told about a request they could neither open nor decide,
and the administrators of other organizations were told about a person who
had never asked them for anything.

The rule, named: whoever may decide a request is told about it, and whoever
is told may decide it.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import status
from sqlalchemy import select

from app.models.notification import Notification
from app.models.organization import Organization
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _admin(db, organization: Organization, *, superuser: bool) -> User:
    user = User(
        email=f'admin_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('testpassword123'),
        full_name='Admin',
        organization_id=organization.id,
        role='admin',
        is_superuser=superuser,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def two_organizations(real_async_db_session, async_test_household):
    """The instance's superuser, an administrator beside them, and one in a
    second organization — committed, since the HTTP client has its own
    session."""
    db = real_async_db_session
    other = Organization(name='Another Organization')
    db.add(other)
    await db.flush()
    people = {
        'superuser': await _admin(db, async_test_household, superuser=True),
        'admin_beside': await _admin(db, async_test_household, superuser=False),
        'admin_elsewhere': await _admin(db, other, superuser=False),
    }
    await db.commit()
    return people


async def _told(db, user: User) -> int:
    rows = await db.scalars(select(Notification).where(Notification.user_id == user.id))
    return len(rows.all())


async def test_the_request_rings_only_for_those_who_can_decide_it(
    real_async_client, real_async_db_session, two_organizations
):
    """Measured on dev: all three administrators were told."""
    response = await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={
            'email': f'asks-{uuid.uuid4().hex[:8]}@example.com',
            'full_name': 'Asking Person',
            'preferred_language': 'en',
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text

    db = real_async_db_session
    told = {name: await _told(db, user) for name, user in two_organizations.items()}
    assert told == {'superuser': 1, 'admin_beside': 0, 'admin_elsewhere': 0}


async def test_whoever_is_told_can_open_the_requests_and_nobody_else(
    real_async_client, two_organizations
):
    """The other half of the rule: the list opens for the one the bell rang
    for, and stays shut for the two it no longer rings for."""
    answers = {}
    for name, user in two_organizations.items():
        response = await real_async_client.get(
            '/api/v1/auth/registration-requests', headers=_auth(user)
        )
        answers[name] = response.status_code

    assert answers == {
        'superuser': status.HTTP_200_OK,
        'admin_beside': status.HTTP_403_FORBIDDEN,
        'admin_elsewhere': status.HTTP_403_FORBIDDEN,
    }


async def test_a_decision_is_told_to_the_others_who_could_have_made_it(
    real_async_client, real_async_db_session, two_organizations, async_test_household
):
    """Approving and refusing ring the bell of the other superusers — not the
    one who decided: four of eight unread entries were an administrator's own
    acts reported back to them."""
    db = real_async_db_session
    colleague = await _admin(db, async_test_household, superuser=True)
    await db.commit()
    email = f'asks-{uuid.uuid4().hex[:8]}@example.com'
    await real_async_client.post(
        '/api/v1/auth/registration-request',
        json={'email': email, 'full_name': 'Asking Person', 'preferred_language': 'en'},
    )
    superuser = two_organizations['superuser']
    listed = await real_async_client.get(
        '/api/v1/auth/registration-requests', headers=_auth(superuser)
    )
    request_id = next(r['id'] for r in listed.json()['items'] if r['email'] == email)

    refused = await real_async_client.post(
        f'/api/v1/auth/registration-requests/{request_id}/reject',
        headers=_auth(superuser),
    )

    assert refused.status_code == status.HTTP_200_OK, refused.text
    told = {name: await _told(db, user) for name, user in two_organizations.items()}
    # The request itself rang once; the decision rang for nobody else of the
    # decider's own bell.
    assert told == {'superuser': 1, 'admin_beside': 0, 'admin_elsewhere': 0}
    # The colleague heard the request and then the decision.
    assert await _told(db, colleague) == 2
