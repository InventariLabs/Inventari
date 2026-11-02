"""Unit tests for app.core.product_profiles.

Verifies that profile definitions match their descriptions and that
key discoverability promises (e.g. 'recipes' in Food & Home) are kept.
These are load-bearing: the public-facing onboarding copy promises
specific modules — if the profile doesn't include them, the best
features stay invisible after signup.
"""

import pytest


class TestProductProfiles:
    """Static registry assertions (no DB)."""

    def test_food_home_includes_recipes(self):
        """'recipes' must be in food_home.default_modules.

        The profile description says 'Includes recipes and shopping lists'
        — the module list must reflect that promise. Before this fix,
        recipes (77-file FE module) was described but not enabled.
        """
        from app.core.product_profiles import get_profile

        profile = get_profile('food_home')
        assert profile is not None
        assert 'recipes' in profile.default_modules
        assert 'shopping_lists' in profile.default_modules

    def test_food_home_description_matches_modules(self):
        """The human-readable description must not promise modules that
        are not in default_modules (false advertising on the onboarding
        screen)."""
        from app.core.product_profiles import get_profile

        profile = get_profile('food_home')
        desc_lower = profile.description.lower()
        # If the description names a module, it must be in default_modules.
        for module_name in ['recipes', 'shopping_lists']:
            if module_name.rstrip('s') in desc_lower or module_name in desc_lower:
                assert module_name in profile.default_modules, (
                    f"'{module_name}' mentioned in description but not in "
                    f'default_modules'
                )

    def test_all_profiles_have_core_modules(self):
        """Every profile must include the non-negotiable core modules."""
        from app.core.product_profiles import get_all_profiles

        required = {'core', 'items', 'locations', 'categories'}
        for profile in get_all_profiles():
            missing = required - set(profile.default_modules)
            assert not missing, (
                f"Profile '{profile.id}' is missing core modules: {missing}"
            )

    def test_no_profile_duplicates_modules(self):
        """A module listed twice in default_modules would cause a double
        system_on_enable call during onboarding."""
        from app.core.product_profiles import get_all_profiles

        for profile in get_all_profiles():
            assert len(profile.default_modules) == len(set(profile.default_modules)), (
                f"Profile '{profile.id}' has duplicate modules: "
                f'{profile.default_modules}'
            )

    def test_no_profile_label_leaks_architecture_vocabulary(self):
        """'Core' is AGENTS.md's word for the domain-neutral backend, not a
        concept any user has. Shipping it as a label is the same leak the
        `maker` module had before it became 'Production'."""
        from app.core.product_profiles import get_all_profiles

        for profile in get_all_profiles():
            assert 'core' not in profile.name.lower(), (
                f"Profile '{profile.id}' fallback name {profile.name!r} uses "
                f"'Core' — an architecture word. See docs/MODULE_NAMES.md "
                f'§ "Workspace mode names".'
            )

    def test_no_profile_description_promises_a_reset(self):
        """Switching a profile keeps every manually enabled module
        (`build_profile_switch_plan` → `manual_kept`) and touches no data.
        A description promising a clean slate is false in the one context
        where the mode is chosen deliberately: an existing installation."""
        from app.core.product_profiles import get_all_profiles

        forbidden = ('from scratch', 'clean slate', 'start over', 'wipe')
        for profile in get_all_profiles():
            lowered = profile.description.lower()
            for phrase in forbidden:
                assert phrase not in lowered, (
                    f"Profile '{profile.id}' description promises {phrase!r}, "
                    f'but a profile switch never resets anything'
                )

    def test_fallback_labels_are_present_and_not_the_identifier(self):
        """The registry fields are the fallback for profiles outside this
        distribution — they must still be usable labels, never the id."""
        from app.core.product_profiles import get_all_profiles

        for profile in get_all_profiles():
            assert profile.name.strip(), f"Profile '{profile.id}' has no name"
            assert profile.description.strip(), (
                f"Profile '{profile.id}' has no description"
            )
            assert profile.name.lower() != profile.id.lower(), (
                f"Profile '{profile.id}' uses its identifier as a label"
            )


class TestLauncherCategories:
    """Launcher profile-awareness.

    The Launcher UI groups modules into categories for at-a-glance navigation.
    Each profile declares which category every module belongs to so that the
    Launcher can render a profile-tailored UI without hard-coding module names.
    """

    def test_launcher_category_literal_is_exported(self):
        from typing import get_args

        from app.core.product_profiles import LauncherCategory

        assert set(get_args(LauncherCategory)) == {
            'core',
            'business',
            'analytics',
            'integrations',
            'system',
        }

    def test_invalid_launcher_category_is_rejected(self):
        from pydantic import ValidationError

        from app.core.product_profiles import ProductProfile

        with pytest.raises(ValidationError):
            ProductProfile(
                id='bad',
                name='Bad',
                description='Invalid category.',
                default_modules=['core'],
                seed_profile='clean_core',
                launcher_categories={'core': 'totally-not-a-real-category'},
            )

    def test_food_home_launcher_categories(self):
        from app.core.product_profiles import get_profile

        profile = get_profile('food_home')
        assert profile is not None
        # Every default module must have a category assignment.
        for module in profile.default_modules:
            assert module in profile.launcher_categories, (
                f"food_home: module '{module}' has no launcher_category"
            )
        # Sanity-check a few expected groupings.
        assert profile.launcher_categories['recipes'] == 'business'
        assert profile.launcher_categories['shopping_lists'] == 'business'
        assert profile.launcher_categories['nutrition'] == 'business'
        assert profile.launcher_categories['stats'] == 'analytics'
        assert profile.launcher_categories['vision'] == 'integrations'

    def test_equipment_wms_launcher_categories(self):
        from app.core.product_profiles import get_profile

        profile = get_profile('equipment_wms')
        assert profile is not None
        for module in profile.default_modules:
            assert module in profile.launcher_categories, (
                f"equipment_wms: module '{module}' has no launcher_category"
            )
        assert profile.launcher_categories['equipment'] == 'business'
        assert profile.launcher_categories['stock_takes'] == 'business'
        assert profile.launcher_categories['stats'] == 'analytics'

    def test_clean_core_launcher_categories_are_empty(self):
        from app.core.product_profiles import get_profile

        profile = get_profile('clean_core')
        assert profile is not None
        # clean_core must NOT impose a categorization; the Launcher falls
        # back to a flat list when categories are empty.
        assert profile.launcher_categories == {}

    def test_launcher_categories_keys_are_unique_modules(self):
        from app.core.product_profiles import get_all_profiles

        for profile in get_all_profiles():
            assert len(profile.launcher_categories) == len(
                set(profile.launcher_categories.keys())
            ), f"Profile '{profile.id}' has duplicate launcher_category keys"

    def test_launcher_categories_keys_are_subset_of_default_modules(self):
        """A category for a module that is not enabled by the profile is
        misleading and would never be rendered. Disallow it."""
        from app.core.product_profiles import get_all_profiles

        for profile in get_all_profiles():
            extra = set(profile.launcher_categories.keys()) - set(
                profile.default_modules
            )
            assert not extra, (
                f"Profile '{profile.id}' declares launcher_categories for "
                f'modules not in default_modules: {extra}'
            )


class TestProfileTheme:
    """Per-profile theme/branding.

    The demo switch must visibly change the app: accent palette and shell
    subtitle. These assertions keep the profile
    registry honest about what the frontend relies on.
    """

    def test_every_profile_declares_a_theme(self):
        """A profile without a theme falls back to the default accent, which
        is the emerald `food_home` declares explicitly — so the neutral mode
        used to be visually indistinguishable from the food one."""
        from app.core.product_profiles import get_all_profiles

        for profile in get_all_profiles():
            assert profile.theme is not None, (
                f"Profile '{profile.id}' declares no theme and would inherit "
                f'the default accent — indistinguishable from food_home'
            )

    def test_theme_variables_cover_full_accent_scale(self):
        from app.core.product_profiles import get_all_profiles

        expected = {
            f'--color-accent-{s}'
            for s in ['50', '100'] + [str(s) for s in range(200, 901, 100)]
        }
        for profile in get_all_profiles():
            if profile.theme is None:
                continue
            assert expected <= set(profile.theme.keys()), (
                f"Profile '{profile.id}' theme must override the full "
                f'accent scale, got {sorted(profile.theme.keys())}'
            )

    def test_theme_variables_cover_full_primary_scale(self):
        """Domain profiles must also repaint
        the primary ramp — it is the dominant action colour of the app, so
        an accent-only override leaves the switch visually invisible."""
        from app.core.product_profiles import get_profile

        expected = {
            f'--color-primary-{s}'
            for s in ['50', '100', '950'] + [str(s) for s in range(200, 901, 100)]
        }
        for profile_id, hue in (
            ('food_home', {'500': '16 185 129', '600': '5 150 105', '950': '2 44 34'}),
            (
                'equipment_wms',
                {'500': '59 130 246', '600': '37 99 235', '950': '23 37 84'},
            ),
            ('clean_core', {'500': '245 158 11', '600': '217 119 6', '950': '69 26 3'}),
        ):
            profile = get_profile(profile_id)
            assert profile is not None and profile.theme is not None
            assert expected <= set(profile.theme.keys()), (
                f"Profile '{profile_id}' theme must override the full "
                f'primary scale, got {sorted(profile.theme.keys())}'
            )
            for step, value in hue.items():
                assert profile.theme[f'--color-primary-{step}'] == value

    def test_theme_values_are_rgb_triplets(self):
        from app.core.product_profiles import get_all_profiles

        for profile in get_all_profiles():
            for var, value in (profile.theme or {}).items():
                parts = value.split(' ')
                assert len(parts) == 3, (
                    f"Profile '{profile.id}' theme value for {var} is not a "
                    f'RGB triplet: {value!r}'
                )
                for part in parts:
                    assert 0 <= int(part) <= 255, (
                        f"Profile '{profile.id}' theme value for {var} has an "
                        f'out-of-range channel: {value!r}'
                    )

    def test_no_two_profiles_share_a_palette(self):
        """A profile switch has to look like a switch. Two modes wearing the
        same hue is the defect this assertion exists to catch."""
        from app.core.product_profiles import get_all_profiles

        seen: dict[str, str] = {}
        for profile in get_all_profiles():
            hue = (profile.theme or {}).get('--color-accent-500')
            assert hue is not None, f"Profile '{profile.id}' has no accent hue"
            assert hue not in seen, (
                f"Profiles '{seen[hue]}' and '{profile.id}' share the accent "
                f'hue {hue!r}'
            )
            seen[hue] = profile.id

    def test_profile_hues_are_the_agreed_ones(self):
        from app.core.product_profiles import get_profile

        for profile_id, hue in (
            ('food_home', '16 185 129'),  # emerald
            ('equipment_wms', '59 130 246'),  # blue
            ('clean_core', '245 158 11'),  # amber
        ):
            profile = get_profile(profile_id)
            assert profile is not None and profile.theme is not None
            assert profile.theme['--color-accent-500'] == hue

    def test_filled_button_background_reads_against_white(self):
        """The filled Button variants paint `primary-700` under a white
        label (components/ui/Button.tsx), so every profile that repaints the
        ramp has to keep that step at WCAG AA. The shell's own token test
        cannot see this: profile themes are applied at runtime."""
        from app.core.product_profiles import get_all_profiles

        def _luminance(triplet: str) -> float:
            channels = []
            for part in triplet.split(' '):
                c = int(part) / 255
                channels.append(
                    c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                )
            r, g, b = channels
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        for profile in get_all_profiles():
            background = (profile.theme or {}).get('--color-primary-700')
            assert background is not None, (
                f"Profile '{profile.id}' does not repaint primary-700, the "
                f'step the filled Button variants use'
            )
            ratio = 1.05 / (_luminance(background) + 0.05)
            assert ratio >= 4.5, (
                f"Profile '{profile.id}' primary-700 {background!r} gives a "
                f'white label only {ratio:.2f}:1 — below WCAG AA'
            )

    def test_branding_subtitle_keys(self):
        from app.core.product_profiles import get_profile

        food = get_profile('food_home')
        equipment = get_profile('equipment_wms')
        clean = get_profile('clean_core')
        assert food is not None and equipment is not None and clean is not None
        assert food.branding == {'subtitle_key': 'profiles.food_home.subtitle'}
        assert equipment.branding == {'subtitle_key': 'profiles.equipment_wms.subtitle'}
        # docs/MODULE_NAMES.md § "Workspace mode names": the neutral mode
        # renders the plain "Inventari" wordmark on purpose. A mode defined by
        # having no domain has nothing to append — this is a decision, not a
        # gap to be filled later.
        assert clean.branding is None


class TestSuggestedModules:
    """The shortlist each profile offers on the second onboarding step.

    ``maker``, ``api_keys`` and ``webhooks`` sit in no profile's
    ``default_modules``, so before this step the only way to reach them was
    Settings -> Modules — which made the first move of three personas "go
    turn it on yourself".
    """

    def test_suggestions_name_modules_that_exist(self):
        """Typo guard: a suggestion nobody ships renders a dead row."""
        from pathlib import Path

        from app.core.module_safety import VIRTUAL_TOGGLEABLE_MODULES
        from app.core.product_profiles import get_all_profiles

        shipped = {p.parent.name for p in Path('app/modules').glob('*/manifest.json')}
        shipped |= set(VIRTUAL_TOGGLEABLE_MODULES)
        for profile in get_all_profiles():
            unknown = set(profile.suggested_modules) - shipped
            assert not unknown, f"Profile '{profile.id}' suggests {sorted(unknown)}"

    def test_suggestions_do_not_repeat_what_the_profile_already_enables(self):
        """A checkbox for something already on reads as broken."""
        from app.core.module_safety import ALWAYS_ON_MODULES
        from app.core.product_profiles import get_all_profiles

        for profile in get_all_profiles():
            overlap = set(profile.suggested_modules) & (
                set(profile.default_modules) | ALWAYS_ON_MODULES
            )
            assert not overlap, (
                f"Profile '{profile.id}' offers modules it already enables: "
                f'{sorted(overlap)}'
            )

    def test_the_household_is_asked_nothing(self):
        """The reason this profile exists. Someone who came to know what is in
        the fridge and what they can cook gets a working application without a
        single question about modules — no goods receipts to cook soup with,
        no sign-off chains, and no second step either.

        An advanced self-hoster who wants API keys or webhooks will find them
        in the module store. Everybody else never has to learn the word.
        """
        from app.core.product_profiles import get_profile

        food = get_profile('food_home')
        assert food is not None
        assert food.suggested_modules == []

    def test_the_three_orphan_modules_are_reachable_from_onboarding(self):
        """The bar is reachability from the onboarding path as a
        whole, not presence in every profile — a household offer listing
        every capability would be the baggage these profiles exist to
        remove."""
        from app.core.product_profiles import get_all_profiles

        reachable: set[str] = set()
        for profile in get_all_profiles():
            reachable |= set(profile.default_modules) | set(profile.suggested_modules)
        missing = {'maker', 'api_keys', 'webhooks'} - reachable
        assert not missing, (
            f'No profile enables or offers {sorted(missing)} — onboarding '
            f'still cannot reach them without a trip to Settings'
        )
