"""Integration tests for the profiles API.

Verifies that the public profile contract (GET /api/v1/profiles and
GET /api/v1/profiles/{id}) exposes the fields the Launcher relies on,
including the profile-aware `launcher_categories` mapping.
"""

import pytest


@pytest.mark.integration
class TestProfilesApi:
    """Public profile contract for the Launcher."""

    def test_list_profiles_returns_launcher_categories(self, client, auth_headers):
        response = client.get('/api/v1/profiles', headers=auth_headers)
        assert response.status_code == 200

        payload = response.json()['items']
        assert isinstance(payload, list)
        assert payload, 'Expected at least one profile'

        for profile in payload:
            assert 'launcher_categories' in profile, (
                f"Profile '{profile.get('id')}' is missing "
                'launcher_categories in the API response'
            )
            assert isinstance(profile['launcher_categories'], dict)

    def test_food_home_profile_serializes_launcher_categories(
        self, client, auth_headers
    ):
        response = client.get('/api/v1/profiles/food_home', headers=auth_headers)
        assert response.status_code == 200

        profile = response.json()
        assert profile['id'] == 'food_home'
        assert profile['launcher_categories']['recipes'] == 'business'
        assert profile['launcher_categories']['stats'] == 'analytics'

    def test_clean_core_profile_has_empty_launcher_categories(
        self, client, auth_headers
    ):
        response = client.get('/api/v1/profiles/clean_core', headers=auth_headers)
        assert response.status_code == 200

        profile = response.json()
        assert profile['id'] == 'clean_core'
        assert profile['launcher_categories'] == {}

    def test_list_profiles_serializes_theme_and_branding(self, client, auth_headers):
        """The FE relies on `theme` and `branding` being present on every
        serialized profile. A profile no longer chooses the start screen —
        the Launcher is everyone's home — so no `home_route` is offered."""
        response = client.get('/api/v1/profiles', headers=auth_headers)
        assert response.status_code == 200

        payload = response.json()['items']
        assert isinstance(payload, list)
        assert payload, 'Expected at least one profile'

        for profile in payload:
            assert 'theme' in profile
            assert 'branding' in profile
            assert 'home_route' not in profile

    def test_domain_profiles_serialize_theme_values(self, client, auth_headers):
        response = client.get('/api/v1/profiles', headers=auth_headers)
        assert response.status_code == 200

        by_id = {profile['id']: profile for profile in response.json()['items']}

        food = by_id['food_home']
        assert food['theme']['--color-accent-500'] == '16 185 129'
        assert food['theme']['--color-accent-600'] == '5 150 105'
        assert food['branding'] == {'subtitle_key': 'profiles.food_home.subtitle'}

        equipment = by_id['equipment_wms']
        assert equipment['theme']['--color-accent-500'] == '59 130 246'
        assert equipment['theme']['--color-accent-600'] == '37 99 235'
        assert equipment['branding'] == {
            'subtitle_key': 'profiles.equipment_wms.subtitle'
        }

        clean = by_id['clean_core']
        # The neutral mode carries its own amber palette: with no
        # theme it inherited the default accent, which is food_home's emerald.
        assert clean['theme']['--color-accent-500'] == '245 158 11'
        assert clean['theme']['--color-accent-600'] == '217 119 6'
        # Unbranded on purpose — see docs/MODULE_NAMES.md
        # § "Workspace mode names".
        assert clean['branding'] is None
