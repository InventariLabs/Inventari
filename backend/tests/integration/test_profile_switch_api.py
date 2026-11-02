"""Integration tests for POST /api/v1/onboarding/switch-profile.

Auth: admin-only. Non-admin users get 403.
Request: ``{"profile_id": "...", "dry_run": true}`` (dry_run default true).
Response: ``ProfileSwitchResponse`` with ``applied`` and ``diff``.
Side effects: no DB writes on dry-run; full transactional apply on apply.

"""

from __future__ import annotations

import pytest
from fastapi import status


@pytest.mark.integration
class TestProfileSwitchApi:
    """Public contract of the profile switch endpoint."""

    def test_dry_run_returns_diff_and_no_apply(
        self, client, auth_headers, db_session, test_household
    ):
        test_household.active_profile_id = 'clean_core'
        test_household.enabled_modules = [
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
        ]
        db_session.commit()

        response = client.post(
            '/api/v1/onboarding/switch-profile',
            json={'profile_id': 'food_home', 'dry_run': True},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body['applied'] is False
        assert body['diff']['to_profile_id'] == 'food_home'
        assert body['diff']['from_profile_id'] == 'clean_core'
        # Detailed diff is present.
        for key in (
            'enable',
            'disable',
            'cascade_disable',
            'unchanged',
            'final_enabled_modules',
            'module_config_overwrite',
        ):
            assert key in body['diff']

    def test_default_dry_run_is_true(
        self, client, auth_headers, db_session, test_household
    ):
        """If the caller omits ``dry_run``, the endpoint must default to
        True — apply is the explicit, conscious opt-in."""
        test_household.active_profile_id = 'clean_core'
        test_household.enabled_modules = [
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
        ]
        db_session.commit()

        response = client.post(
            '/api/v1/onboarding/switch-profile',
            json={'profile_id': 'food_home'},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body['applied'] is False

    def test_unknown_profile_returns_404(self, client, auth_headers):
        response = client.post(
            '/api/v1/onboarding/switch-profile',
            json={'profile_id': 'not_a_real_profile', 'dry_run': True},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_missing_profile_id_returns_422(self, client, auth_headers):
        response = client.post(
            '/api/v1/onboarding/switch-profile',
            json={},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_apply_changes_active_profile_id(
        self, client, auth_headers, db_session, test_household
    ):
        # Set up an org with clean_core modules; the auth_headers user
        # already belongs to it via the fixture.
        test_household.active_profile_id = None
        test_household.enabled_modules = [
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
        ]
        db_session.commit()

        response = client.post(
            '/api/v1/onboarding/switch-profile',
            json={'profile_id': 'clean_core', 'dry_run': False},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body['applied'] is True
        assert body['diff']['to_profile_id'] == 'clean_core'
        # The response body includes the refreshed org so the API
        # contract is the canonical source of truth for the new state.
        assert body['organization'] is not None
        assert body['organization']['active_profile_id'] == 'clean_core'
        assert body['organization']['onboarding_completed'] is True

    def test_dry_run_does_not_modify_org(
        self, client, auth_headers, db_session, test_household
    ):
        test_household.active_profile_id = 'clean_core'
        test_household.enabled_modules = [
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
        ]
        db_session.commit()

        response = client.post(
            '/api/v1/onboarding/switch-profile',
            json={'profile_id': 'food_home', 'dry_run': True},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify the org row was NOT modified.
        db_session.refresh(test_household)
        assert test_household.active_profile_id == 'clean_core'

    def test_manual_module_survives_apply(
        self, client, auth_headers, db_session, test_household
    ):
        """Delta semantics: a module enabled manually (not owned by the
        source profile) must survive the switch — only the source
        profile's own defaults are disabled."""
        test_household.active_profile_id = 'food_home'
        test_household.enabled_modules = [
            'core',
            'items',
            'locations',
            'categories',
            'shopping_lists',
            'recipes',
            'stock_takes',
            'nutrition',
            'vision',
            'stats',
            'api_keys',  # enabled manually — not part of any profile
        ]
        db_session.commit()

        response = client.post(
            '/api/v1/onboarding/switch-profile',
            json={'profile_id': 'equipment_wms', 'dry_run': False},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body['applied'] is True
        assert 'api_keys' in body['diff']['manual_kept']
        assert 'api_keys' not in body['diff']['disable_all']

        db_session.refresh(test_household)
        assert 'api_keys' in test_household.enabled_modules
        # Food-only defaults are really removed by the apply — confirms
        # the disable hooks ran (stale orgs in dev DB predate this fix).
        assert 'shopping_lists' not in test_household.enabled_modules
        assert 'recipes' not in test_household.enabled_modules

    def test_legacy_org_switch_is_additive(
        self, client, auth_headers, db_session, test_household
    ):
        """An org without ``active_profile_id`` has no source profile, so
        the switch is purely additive — nothing is disabled."""
        test_household.active_profile_id = None
        test_household.enabled_modules = [
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
            'webhooks',
        ]
        db_session.commit()

        response = client.post(
            '/api/v1/onboarding/switch-profile',
            json={'profile_id': 'clean_core', 'dry_run': False},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body['diff']['disable'] == []
        assert body['diff']['cascade_disable'] == []
        assert 'webhooks' in body['diff']['manual_kept']

        db_session.refresh(test_household)
        assert 'webhooks' in test_household.enabled_modules

    def test_preview_returns_manual_kept(
        self, client, auth_headers, db_session, test_household
    ):
        test_household.active_profile_id = 'clean_core'
        test_household.enabled_modules = [
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
            'webhooks',
        ]
        db_session.commit()

        response = client.post(
            '/api/v1/onboarding/switch-profile',
            json={'profile_id': 'food_home', 'dry_run': True},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert 'manual_kept' in body['diff']
        assert 'webhooks' in body['diff']['manual_kept']
