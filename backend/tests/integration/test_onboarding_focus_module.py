"""Onboarding with a single chosen module instead of a product profile.

The fourth onboarding choice: one module that is the whole application.
Completing setup with ``focus_module`` applies the neutral profile and then
enters focus mode through the same service Settings -> Work mode uses, so
leaving the mode restores the snapshot taken at entry.
"""

import uuid

import pytest
from fastapi import status
from sqlalchemy import select

from app.models.audit_log import AuditLog, AuditTargetType
from app.models.organization import Organization
from app.models.user import User
from app.services.focus_mode_service import FocusModeApplyError
from app.services.token_service import create_access_token

SETUP_URL = '/api/v1/onboarding/setup'
FOCUS_URL = '/api/v1/modules/focus'
MY_MODULES_URL = '/api/v1/modules/my'
MY_ORG_URL = '/api/v1/organizations/my'


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _fresh_admin(session) -> User:
    org = Organization(
        name=f'Focus Onboarding {uuid.uuid4().hex[:8]}', enabled_modules=['core']
    )
    session.add(org)
    await session.flush()
    user = User(
        email=f'focus_onb_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password='x',
        full_name='Onboarding Admin',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    session.add(user)
    await session.commit()
    return user


@pytest.mark.integration
@pytest.mark.asyncio
class TestOnboardingWithAFocusModule:
    async def test_finishing_with_a_module_leaves_the_org_in_focus_mode(
        self, real_async_client, real_async_db_session
    ):
        user = await _fresh_admin(real_async_db_session)

        setup = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core', 'focus_module': 'recipes'},
            headers=_auth(user),
        )
        assert setup.status_code == status.HTTP_200_OK, setup.text
        assert setup.json()['onboarding_completed'] is True

        focus = await real_async_client.get(FOCUS_URL, headers=_auth(user))
        assert focus.json()['applied'] is True
        assert focus.json()['focus_module'] == 'recipes'

    async def test_leaving_keeps_the_module_that_was_chosen(
        self, real_async_client, real_async_db_session
    ):
        user = await _fresh_admin(real_async_db_session)
        await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core', 'focus_module': 'recipes'},
            headers=_auth(user),
        )

        left = await real_async_client.delete(FOCUS_URL, headers=_auth(user))
        assert left.status_code == status.HTTP_200_OK, left.text
        assert left.json()['focus_module'] is None
        assert 'recipes' in left.json()['enabled_modules']
        assert 'stock_takes' in left.json()['enabled_modules']

        mine = await real_async_client.get(MY_MODULES_URL, headers=_auth(user))
        assert 'recipes' in mine.json()

    async def test_leaving_journals_each_module_it_switches(
        self, real_async_client, real_async_db_session
    ):
        user = await _fresh_admin(real_async_db_session)
        await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core', 'focus_module': 'recipes'},
            headers=_auth(user),
        )
        await real_async_client.delete(FOCUS_URL, headers=_auth(user))

        rows = (
            await real_async_db_session.execute(
                select(AuditLog).where(
                    AuditLog.organization_id == user.organization_id,
                    AuditLog.target_type == AuditTargetType.MODULE,
                )
            )
        ).scalars()
        switches = [
            r.snapshot for r in rows if 'enabled' in (r.snapshot or {}).get('after', {})
        ]
        # Leaving restores the pre-choice set: the modules focus switched off
        # are switched back on, one entry each, and the chosen one is not
        # among the entries because it stays on.
        assert switches
        assert all(s['after'] == {'enabled': True} for s in switches)
        assert 'recipes' not in {s['name'] for s in switches}

    async def test_an_unknown_module_is_refused_and_onboarding_stays_open(
        self, real_async_client, real_async_db_session
    ):
        user = await _fresh_admin(real_async_db_session)

        setup = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core', 'focus_module': 'no_such_module'},
            headers=_auth(user),
        )
        assert setup.status_code == status.HTTP_409_CONFLICT, setup.text
        # The same body the focus route answers, context and language included.
        detail = setup.json()['detail']
        assert detail['code'] == 'unknown_module'
        assert detail['module'] == 'no_such_module'
        assert detail['lang'] == 'en'

        focus = await real_async_client.get(FOCUS_URL, headers=_auth(user))
        assert focus.json()['applied'] is False

    async def test_a_failure_entering_the_mode_leaves_onboarding_open(
        self, real_async_client, real_async_db_session, monkeypatch
    ):
        """Nothing is kept from a choice that was cut short: reopening shows onboarding again."""
        from app.api import onboarding

        real_enter = onboarding.enter_focus_mode
        calls = {'n': 0}

        async def enter_once_broken(**kwargs):
            calls['n'] += 1
            if calls['n'] == 1:
                raise FocusModeApplyError('interrupted')
            return await real_enter(**kwargs)

        monkeypatch.setattr(onboarding, 'enter_focus_mode', enter_once_broken)
        user = await _fresh_admin(real_async_db_session)
        body = {'profile_id': 'clean_core', 'focus_module': 'recipes'}

        first = await real_async_client.post(SETUP_URL, json=body, headers=_auth(user))
        assert first.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        # What the app reads on the next visit to decide whether to show onboarding.
        mine = await real_async_client.get(MY_ORG_URL, headers=_auth(user))
        assert not mine.json()['onboarding_completed']
        assert 'active_profile_id' in mine.json()
        assert not mine.json()['active_profile_id']
        focus = await real_async_client.get(FOCUS_URL, headers=_auth(user))
        assert focus.json()['applied'] is False

        retry = await real_async_client.post(SETUP_URL, json=body, headers=_auth(user))
        assert retry.status_code == status.HTTP_200_OK, retry.text
        focus = await real_async_client.get(FOCUS_URL, headers=_auth(user))
        assert focus.json()['applied'] is True
        assert focus.json()['focus_module'] == 'recipes'

    async def test_a_second_request_after_a_finished_choice_is_still_refused(
        self, real_async_client, real_async_db_session
    ):
        user = await _fresh_admin(real_async_db_session)
        body = {'profile_id': 'clean_core', 'focus_module': 'recipes'}
        assert (
            await real_async_client.post(SETUP_URL, json=body, headers=_auth(user))
        ).status_code == status.HTTP_200_OK

        again = await real_async_client.post(SETUP_URL, json=body, headers=_auth(user))
        assert again.status_code == status.HTTP_409_CONFLICT
        assert again.json()['detail']['code'] == 'ONBOARDING_ALREADY_COMPLETED'

    async def test_a_finished_onboarding_is_not_reopened_under_another_profile(
        self, real_async_client, real_async_db_session
    ):
        user = await _fresh_admin(real_async_db_session)
        done = await real_async_client.post(
            SETUP_URL, json={'profile_id': 'clean_core'}, headers=_auth(user)
        )
        assert done.status_code == status.HTTP_200_OK

        late = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'food_home', 'focus_module': 'recipes'},
            headers=_auth(user),
        )
        assert late.status_code == status.HTTP_409_CONFLICT
