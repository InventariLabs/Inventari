"""Access control and replay guard on `POST /onboarding/setup`.

Applying a profile rewrites the organization: it seeds default data, enables
the profile's modules and overwrites module config. That is an admin-level
operation, and it belongs to first-run only — an already-onboarded org changes
profile through `/onboarding/switch-profile`, which plans the diff instead of
re-seeding blind.
"""

import pytest
from fastapi import status

from app.services.token_service import create_access_token

SETUP_URL = '/api/v1/onboarding/setup'


def _auth(user):
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.integration
@pytest.mark.asyncio
class TestOnboardingSetupAccess:
    async def test_non_admin_is_rejected(
        self, real_async_client, real_async_db_session, async_test_user2
    ):
        await real_async_db_session.commit()
        assert async_test_user2.role == 'user'

        response = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core'},
            headers=_auth(async_test_user2),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.text

    async def test_admin_applies_the_profile(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core'},
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['active_profile_id'] == 'clean_core'

    async def test_the_name_the_founder_gave_is_the_name_the_organization_keeps(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={
                'profile_id': 'clean_core',
                'organization_name': '  Kowalski Bakery ',
            },
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['name'] == 'Kowalski Bakery'

    async def test_setup_journals_the_module_set_it_established(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """The wizard decides the module set the org runs with.

        The switch route records the same shape; setup recorded nothing at
        all, so a fresh organization's journal could not say what it was
        onboarded as.
        """
        from sqlalchemy import select

        from app.models.audit_log import AuditLog

        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core'},
            headers=_auth(async_test_user),
        )
        assert response.status_code == status.HTTP_200_OK, response.text

        entries = (
            await real_async_db_session.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == async_test_household.id,
                    AuditLog.target_type == 'product_profile',
                )
            )
        ).all()
        assert entries, 'the wizard rewrote the module set and named nothing'
        snapshot = entries[0].snapshot
        assert snapshot['name'] == 'clean_core'
        assert snapshot['after']['profile_id'] == 'clean_core'
        assert 'items' in snapshot['after']['enabled_modules']

    async def test_second_setup_is_rejected(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        async_test_household.onboarding_completed = True
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core'},
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text

    async def test_setup_persists_selected_currency(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """The currency chosen on the onboarding screen lands on the
        organization, so fleet valuation sums in the tenant's currency."""
        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core', 'currency': 'PLN'},
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['currency'] == 'PLN'

    async def test_setup_rejects_malformed_currency(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core', 'currency': 'poland'},
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.integration
@pytest.mark.asyncio
class TestOnboardingSetupCountry:
    """The country decides the tax rule, so onboarding asks for it.

    Settings was the only place that set it, and a fresh organization in
    Poland, Germany or the UK had no standard rate and no partner rule until
    someone found the field.
    """

    async def test_setup_persists_the_chosen_country(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core', 'country': 'de'},
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['country'] == 'DE'

    async def test_setup_without_a_country_leaves_it_unset(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core'},
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['country'] is None

    async def test_setup_rejects_a_code_that_is_not_a_country(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core', 'country': 'ZZ'},
            headers=_auth(async_test_user),
        )

        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        ), response.text


@pytest.mark.integration
@pytest.mark.asyncio
class TestOnboardingCountryPreset:
    """The setup screen asks which document preset a country comes with."""

    async def test_names_the_preset_of_a_country_that_has_one(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/onboarding/country-preset?country=de',
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json() == {'preset': 'DE Lager'}

    @pytest.mark.parametrize('query', ['?country=JP', ''])
    async def test_has_no_preset_for_other_or_unset_countries(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
        query,
    ):
        await real_async_db_session.commit()

        response = await real_async_client.get(
            f'/api/v1/onboarding/country-preset{query}',
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json() == {'preset': None}

    async def test_setup_accepts_the_offer(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={
                'profile_id': 'equipment_wms',
                'country': 'DE',
                'use_country_preset': True,
            },
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        from app.modules.warehouse.document_profile_service import get_profile

        stored = await get_profile(real_async_db_session, async_test_household.id)
        assert stored is not None
        assert stored.name == 'DE Lager'


@pytest.mark.integration
@pytest.mark.asyncio
class TestOnboardingSetupTimeZone:
    """The zone the setup screen's browser reported lands on the row.

    The zone decides when a day starts for expiry dates, inventory periods
    and reports, so a fresh organization sitting on UTC whatever the browser
    said moves a Polish household's expiry day two hours late — and nothing
    on the path said so. The field is a hint from a browser, though, so an
    answer this server cannot read must not fail the one step that stands
    between the reader and the application.
    """

    async def test_setup_takes_the_time_zone_the_browser_reported(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core', 'timezone': 'Europe/Warsaw'},
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['timezone'] == 'Europe/Warsaw'

    async def test_an_unreadable_time_zone_does_not_block_onboarding(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """200 with the default, not 422.

        The name comes from a browser whose tzdb may be newer than the
        server's, and a 422 here has no answer the reader could give —
        onboarding is the only step to the application. The column keeps
        UTC, the same degradation ``org_timezone_async`` performs on read.
        """
        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core', 'timezone': 'Mars/Olympus_Mons'},
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['timezone'] == 'UTC'


@pytest.mark.integration
@pytest.mark.asyncio
class TestOnboardingSetupSelection:
    """The second step's answer has to survive the trip to the service.

    The logic lives in `onboarding_service`; what these cover is the wiring,
    which is where a rename fails silently — a dropped `modules` would leave
    every organization on its preset and no test would notice.
    """

    async def test_the_selection_reaches_the_organization(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={
                'profile_id': 'clean_core',
                'modules': ['stock_takes', 'api_keys'],
            },
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        enabled = response.json()['enabled_modules']
        assert 'api_keys' in enabled

    async def test_a_module_outside_the_offer_is_refused(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """400, not 404. The endpoint maps ValueError to "no such
        organization", and a refusal that borrowed that code would send the
        reader looking for the wrong problem."""
        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()

        response = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'food_home', 'modules': ['warehouse']},
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text

    async def test_setup_clears_the_module_cache_after_the_commit(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
        monkeypatch,
    ):
        """The caches are cleared once the new profile is committed.

        Cleared earlier, a read in the gap re-caches the old committed set
        for the full TTL. The probe records whether the write was already
        committed when the key was deleted.
        """
        from sqlalchemy import select

        from app.models.organization import Organization

        async_test_household.onboarding_completed = False
        await real_async_db_session.commit()
        org_id = async_test_household.id
        seen: list[bool] = []

        async def _probe(*keys):
            async with real_async_db_session.bind.connect() as conn:
                done = await conn.scalar(
                    select(Organization.onboarding_completed).where(
                        Organization.id == org_id
                    )
                )
            seen.append(bool(done))

        monkeypatch.setattr('app.api.onboarding.cache_delete', _probe)

        response = await real_async_client.post(
            SETUP_URL,
            json={'profile_id': 'clean_core'},
            headers=_auth(async_test_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert seen == [True]
