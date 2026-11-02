"""The toggle → onboarding walk.

A module switched on through POST /modules/toggle before onboarding was
finished, and not offered by the profile the admin then chooses, used to be
dropped when 'Get started' was pressed: the setup overwrote
``enabled_modules`` with the profile's chosen set and only logged the loss.
The admin's explicit choice is kept, and GET /modules/my still serves it.
"""

import uuid

import pytest
from fastapi import status

from app.models.organization import Organization
from app.models.user import User
from app.services.token_service import create_access_token

TOGGLE_URL = '/api/v1/modules/toggle'
SETUP_URL = '/api/v1/onboarding/setup'
MY_MODULES_URL = '/api/v1/modules/my'


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheToggleBeforeOnboardingSurvivesIt:
    async def test_a_module_outside_the_offer_is_still_served_after_get_started(
        self,
        real_async_client,
        real_async_db_session,
    ):
        """The scenario, walked through the API: an org that
        has not finished onboarding switches 'warehouse' on — Food & Home
        does not offer it — then presses 'Get started'. Fails on dev, where
        the setup replaces the enabled set and the module disappears from
        what GET /modules/my serves."""
        org = Organization(
            name=f'Toggle Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        user = User(
            email=f'toggle_admin_{uuid.uuid4().hex[:8]}@example.com',
            hashed_password='x',
            full_name='Onboarding Admin',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(user)
        await real_async_db_session.commit()

        toggled = await real_async_client.post(
            TOGGLE_URL,
            json={'module_name': 'warehouse', 'enabled': True},
            headers=_auth(user),
        )
        assert toggled.status_code == status.HTTP_200_OK, toggled.text

        setup = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'food_home'},
            headers=_auth(user),
        )
        assert setup.status_code == status.HTTP_200_OK, setup.text

        served = await real_async_client.get(MY_MODULES_URL, headers=_auth(user))
        assert served.status_code == status.HTTP_200_OK, served.text
        assert 'warehouse' in served.json()
