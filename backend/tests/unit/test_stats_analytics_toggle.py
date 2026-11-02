"""
Analytics is a per-profile feature, not a fixed tab.

Rotation, spend forecasts and purchase patterns need months of history and
dozens of transactions; a home pantry with forty items gets noise out of
them, not a conclusion. The contract mirrors the `recipes.enable_cost_calculation`
pilot (tests/unit/test_pilot_feature_toggle.py):

  1. The stats module declares `enable_analytics` in its settings schema,
     default True.
  2. `food_home` presets it to False, `equipment_wms` declares True
     explicitly; the custom profile declares nothing and gets the default.
  3. `GET /stats/config` serves the effective value to every stats:read
     user, so the tab and the route can refuse together (the admin-only
     settings endpoint cannot — a viewer sees the tab too).

The home profile extends the same contract to `show_inventory_value` — the total
stock value on the always-visible overview is a business metric read off a
cost ledger a home pantry does not keep, so `food_home` presets it off too.
This is also the evidence that a profile change alters behaviour (the
settings the org runs with), not only palette and wordmark.
"""

from __future__ import annotations

import pytest


def test_stats_module_declares_enable_analytics() -> None:
    from app.modules.stats.module import module

    schema = module.get_settings_schema()
    assert schema is not None
    field = schema['properties']['enable_analytics']  # type: ignore[index]
    assert field['type'] == 'boolean'  # type: ignore[index]
    assert field['default'] is True  # type: ignore[index]
    assert module.get_default_settings()['enable_analytics'] is True


def test_stats_module_declares_show_inventory_value() -> None:
    from app.modules.stats.module import module

    schema = module.get_settings_schema()
    assert schema is not None
    field = schema['properties']['show_inventory_value']  # type: ignore[index]
    assert field['type'] == 'boolean'  # type: ignore[index]
    assert field['default'] is True  # type: ignore[index]
    assert module.get_default_settings()['show_inventory_value'] is True


def test_food_home_disables_analytics() -> None:
    from app.core.product_profiles import get_profile

    profile = get_profile('food_home')
    assert profile is not None
    assert profile.module_config['stats']['enable_analytics'] is False


def test_food_home_hides_inventory_value() -> None:
    from app.core.product_profiles import get_profile

    profile = get_profile('food_home')
    assert profile is not None
    assert profile.module_config['stats']['show_inventory_value'] is False


def test_equipment_wms_enables_analytics_explicitly() -> None:
    """A profile says what it wants — the business profile names True rather
    than inheriting a default it could silently lose."""
    from app.core.product_profiles import get_profile

    profile = get_profile('equipment_wms')
    assert profile is not None
    assert profile.module_config['stats']['enable_analytics'] is True
    assert profile.module_config['stats']['show_inventory_value'] is True


def test_custom_profile_declares_no_stats_config() -> None:
    """clean_core has no stats in default_modules; an override would be dead
    config the onboarding service skips with a warning."""
    from app.core.product_profiles import PRODUCT_PROFILES

    custom = next(
        p
        for p in PRODUCT_PROFILES.values()
        if p.seed_profile is None or p.id == 'clean_core'
    )
    assert 'stats' not in custom.module_config


@pytest.mark.integration
class TestStatsConfigEndpoint:
    """The value the interface reads, at the module's own read permission."""

    def test_config_defaults_to_enabled(self, client, auth_headers):
        from fastapi import status

        response = client.get('/api/v1/stats/config', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['enable_analytics'] is True
        assert response.json()['show_inventory_value'] is True

    def test_config_reflects_the_org_setting(
        self, client, auth_headers, test_household, db_session
    ):
        from fastapi import status

        test_household.settings = {
            'module:stats': {
                'enable_analytics': False,
                'show_inventory_value': False,
            }
        }
        db_session.commit()

        response = client.get('/api/v1/stats/config', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['enable_analytics'] is False
        assert response.json()['show_inventory_value'] is False

    def test_config_reflects_each_setting_independently(
        self, client, auth_headers, test_household, db_session
    ):
        """The two toggles answer different questions; flipping one must not
        drag the other."""
        from fastapi import status

        test_household.settings = {'module:stats': {'show_inventory_value': False}}
        db_session.commit()

        response = client.get('/api/v1/stats/config', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['enable_analytics'] is True
        assert response.json()['show_inventory_value'] is False
