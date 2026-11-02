"""On a demo, one click signs a visitor in to an organization of their own.

``POST /api/v1/demo/sandbox`` takes a seeded organization off the pool the
demo-reset service keeps (``manage.py demo fill-pool``) and signs the visitor
in as its administrator. The sandboxes here are opened but not seeded: what is
under test is the handing out, and ``test_demo_sandboxes_are_separate_
organizations`` covers what the seed puts in them.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import app.api.demo as demo_api
from app.cli.commands_demo import open_sandbox_account
from app.config import settings
from app.core.limiter import limiter
from app.models.user import User
from app.services.demo_sandbox_service import add_to_pool_async, pool_state_async
from app.services.token_service import create_demo_sandbox_token

pytestmark = pytest.mark.integration

SANDBOX = '/api/v1/demo/sandbox'


@pytest.fixture
def demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, 'INVENTARI_DEMO', True)


async def _offer(db: Session, adb: AsyncSession, count: int = 1) -> list[uuid.UUID]:
    """Open ``count`` sandboxes and put them on the pool; return their admins."""
    admins = []
    for _ in range(count):
        org_id, user_id, _email = open_sandbox_account(db)
        await add_to_pool_async(adb, org_id, user_id)
        admins.append(user_id)
    await adb.commit()
    return admins


async def _me(client: AsyncClient, access_token: str) -> dict:
    response = await client.get(
        '/api/v1/auth/me', headers={'Authorization': f'Bearer {access_token}'}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _org_of(db: Session, me: dict) -> uuid.UUID:
    account = db.get(User, uuid.UUID(me['id']))
    assert account is not None and account.organization_id is not None
    return account.organization_id


async def test_outside_a_demo_the_route_is_not_there(
    real_async_client: AsyncClient,
) -> None:
    assert settings.INVENTARI_DEMO is False
    response = await real_async_client.post(SANDBOX, json={})
    assert response.status_code == 404, response.text


async def test_one_click_signs_in_the_administrator_of_a_new_organization(
    demo, real_async_client: AsyncClient, real_async_db_session, db_session
) -> None:
    (admin_id,) = await _offer(db_session, real_async_db_session)

    response = await real_async_client.post(SANDBOX, json={})

    assert response.status_code == 200, response.text
    me = await _me(real_async_client, response.json()['access_token'])
    account = db_session.get(User, admin_id)
    db_session.refresh(account)
    assert me['id'] == str(admin_id)
    assert me['role'] == 'admin'
    assert me['is_superuser'] is False
    assert account.is_active, 'handing the sandbox out activates its account'
    assert 'refresh_token' in response.cookies
    assert demo_api.SANDBOX_COOKIE in response.cookies


async def test_the_sandbox_log_opens_with_the_visitor_taking_it(
    demo, real_async_client: AsyncClient, real_async_db_session, db_session
) -> None:
    (admin_id,) = await _offer(db_session, real_async_db_session)
    token = (await real_async_client.post(SANDBOX, json={})).json()['access_token']

    response = await real_async_client.get(
        '/api/v1/audit-log',
        params={'target_type': 'organization'},
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 200, response.text
    entries = response.json()['items']
    assert [(e['action'], e['user_id']) for e in entries] == [('USE', str(admin_id))]


async def test_the_new_account_speaks_the_language_the_visitor_was_reading(
    demo, real_async_client: AsyncClient, real_async_db_session, db_session
) -> None:
    """Signing in must not switch a visitor reading Polish to English."""
    await _offer(db_session, real_async_db_session)

    response = await real_async_client.post(SANDBOX, json={'preferred_language': 'pl'})

    assert response.status_code == 200, response.text
    me = await _me(real_async_client, response.json()['access_token'])
    assert me['preferred_language'] == 'pl'


async def test_a_waiting_sandbox_cannot_be_signed_in_to(
    real_async_db_session, db_session
) -> None:
    """Until a visitor is handed it, the account is inactive: no way in."""
    (admin_id,) = await _offer(db_session, real_async_db_session)
    assert db_session.get(User, admin_id).is_active is False


async def test_the_same_browser_returns_to_its_own_organization(
    demo, real_async_client: AsyncClient, real_async_db_session, db_session
) -> None:
    await _offer(db_session, real_async_db_session, count=2)

    first = await real_async_client.post(SANDBOX, json={})
    again = await real_async_client.post(SANDBOX, json={})

    assert again.status_code == 200, again.text
    mine = await _me(real_async_client, first.json()['access_token'])
    back = await _me(real_async_client, again.json()['access_token'])
    assert back['id'] == mine['id']
    state = await pool_state_async(real_async_db_session)
    assert (state.ready, state.claimed) == (1, 1)


async def test_starting_over_hands_out_a_new_organization(
    demo, real_async_client: AsyncClient, real_async_db_session, db_session
) -> None:
    await _offer(db_session, real_async_db_session, count=2)

    first = await real_async_client.post(SANDBOX, json={})
    fresh = await real_async_client.post(SANDBOX, json={'fresh': True})

    assert fresh.status_code == 200, fresh.text
    old = await _me(real_async_client, first.json()['access_token'])
    new = await _me(real_async_client, fresh.json()['access_token'])
    assert new['id'] != old['id']
    assert _org_of(db_session, new) != _org_of(db_session, old)
    # And the browser now returns to the new one, not the old.
    again = await real_async_client.post(SANDBOX, json={})
    assert (await _me(real_async_client, again.json()['access_token']))['id'] == new[
        'id'
    ]


async def test_after_the_reset_the_way_back_leads_to_a_new_sandbox(
    demo, real_async_client: AsyncClient, real_async_db_session, db_session
) -> None:
    """The reset deletes the account the cookie names; the visitor gets another."""
    (admin_id,) = await _offer(db_session, real_async_db_session)
    real_async_client.cookies.set(
        demo_api.SANDBOX_COOKIE, create_demo_sandbox_token(uuid.uuid4())
    )

    response = await real_async_client.post(SANDBOX, json={})

    assert response.status_code == 200, response.text
    me = await _me(real_async_client, response.json()['access_token'])
    assert me['id'] == str(admin_id)


async def test_the_way_back_opens_no_account_the_pool_did_not_hand_out(
    demo,
    real_async_client: AsyncClient,
    real_async_db_session,
    db_session,
    test_user,
) -> None:
    """A cookie naming the operator's account (or anyone's) is a cookie naming nobody."""
    (admin_id,) = await _offer(db_session, real_async_db_session)
    real_async_client.cookies.set(
        demo_api.SANDBOX_COOKIE, create_demo_sandbox_token(test_user.id)
    )

    response = await real_async_client.post(SANDBOX, json={})

    assert response.status_code == 200, response.text
    me = await _me(real_async_client, response.json()['access_token'])
    assert me['id'] == str(admin_id)


async def test_the_way_back_is_not_an_access_token(
    demo, real_async_client: AsyncClient, real_async_db_session, db_session
) -> None:
    await _offer(db_session, real_async_db_session)
    response = await real_async_client.post(SANDBOX, json={})
    way_back = response.cookies[demo_api.SANDBOX_COOKIE]

    me = await real_async_client.get(
        '/api/v1/auth/me', headers={'Authorization': f'Bearer {way_back}'}
    )
    assert me.status_code == 401, me.text


async def test_an_empty_pool_is_a_plain_refusal(
    demo, real_async_client: AsyncClient
) -> None:
    response = await real_async_client.post(SANDBOX, json={})
    assert response.status_code == 503, response.text
    assert response.json()['detail']['code'] == 'DEMO_SANDBOX_POOL_EMPTY'


async def test_the_daily_cap_is_a_plain_refusal(
    demo,
    monkeypatch: pytest.MonkeyPatch,
    real_async_client: AsyncClient,
    real_async_db_session,
    db_session,
) -> None:
    monkeypatch.setattr(settings, 'DEMO_SANDBOX_DAILY_CAP', 1)
    await _offer(db_session, real_async_db_session, count=2)

    assert (await real_async_client.post(SANDBOX, json={})).status_code == 200
    refused = await real_async_client.post(SANDBOX, json={'fresh': True})

    assert refused.status_code == 429, refused.text
    assert refused.json()['detail']['code'] == 'DEMO_SANDBOX_CAP_REACHED'
    state = await pool_state_async(real_async_db_session)
    assert (state.ready, state.claimed) == (1, 1), 'a refused click took nothing'


async def test_one_address_asks_only_so_often(
    demo,
    monkeypatch: pytest.MonkeyPatch,
    real_async_client: AsyncClient,
    real_async_db_session,
    db_session,
) -> None:
    """Counted per address in the stack's Redis, in a bucket no other test shares."""
    monkeypatch.setattr(limiter, 'enabled', True)
    monkeypatch.setattr(settings, 'DEMO_SANDBOX_RATE_LIMIT', '2/hour')
    bucket = f'demo-sandbox-test-{uuid.uuid4().hex}'
    monkeypatch.setattr(demo_api, 'get_client_ip', lambda _request: bucket)
    await _offer(db_session, real_async_db_session, count=3)

    answers = [
        (await real_async_client.post(SANDBOX, json={'fresh': True})).status_code
        for _ in range(3)
    ]

    assert answers == [200, 200, 429]
