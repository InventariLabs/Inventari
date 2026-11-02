"""Unit tests for app.services.profile_switch_service — dry-run path.

The dry-run service computes the diff for a profile switch WITHOUT
performing any DB writes, lifecycle hooks, seed, or cache invalidation.
It is a pure read-only operation intended for the Admin UI to preview
the impact before applying.

"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core._base_module import BaseModule
from app.core._module_declarations import ModuleMetadata
from app.core.product_profiles import ProductProfile
from app.services.profile_switch_planner import ProfileSwitchError
from app.services.profile_switch_service import preview_profile_switch


class _SniffingModule(BaseModule):
    """A module whose hooks raise if they are called during a dry-run."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name=self._name,
            display_name=self._name.title(),
            description='Sniffing module.',
            icon='box',
        )

    def register_routes(self):
        raise NotImplementedError

    async def system_on_enable(
        self, organization_id: str, db: Any, *, user: Any | None = None
    ) -> None:
        raise AssertionError('system_on_enable must not be called in dry-run')

    async def system_on_disable(self, organization_id: str, db: Any) -> None:
        raise AssertionError('system_on_disable must not be called in dry-run')

    def on_enable(self, organization_id: str, context: Any) -> None:
        raise AssertionError('on_enable must not be called in dry-run')

    def on_disable(self, organization_id: str, context: Any) -> None:
        raise AssertionError('on_disable must not be called in dry-run')


def _profile(
    profile_id: str = 'food_home',
    modules: Sequence[str] | None = None,
) -> ProductProfile:
    return ProductProfile(
        id=profile_id,
        name=profile_id.title(),
        description='Test profile.',
        default_modules=list(
            modules or ['core', 'items', 'locations', 'categories', 'stock_takes']
        ),
        seed_profile='clean_core',
    )


def _org(
    enabled_modules: Sequence[str] | None = None,
    *,
    active_profile_id: str | None = None,
) -> MagicMock:
    org = MagicMock()
    org.id = 'org-1'
    org.enabled_modules = list(enabled_modules or [])
    org.active_profile_id = active_profile_id
    return org


@pytest.mark.unit
class TestPreviewProfileSwitch:
    """The dry-run path returns a deterministic plan without side effects."""

    def test_preview_returns_plan_with_correct_target(self):
        org = _org(enabled_modules=['core', 'items', 'locations', 'categories'])
        profile = _profile('food_home')

        plan = preview_profile_switch(
            organization=org,
            profile=profile,
            modules=[_SniffingModule(m) for m in profile.default_modules],
        )

        assert plan.to_profile_id == 'food_home'
        assert 'stock_takes' in plan.enable
        # Always-on modules are present in final state.
        assert 'core' in plan.final_enabled_modules
        assert 'items' in plan.final_enabled_modules

    def test_preview_does_not_mutate_organization(self):
        org = _org(enabled_modules=['core', 'items', 'locations', 'categories'])
        snapshot = {
            'enabled_modules': list(org.enabled_modules),
            'active_profile_id': org.active_profile_id,
        }
        profile = _profile('food_home')

        preview_profile_switch(
            organization=org,
            profile=profile,
            modules=[_SniffingModule(m) for m in profile.default_modules],
        )

        # The organization object must not be mutated by the preview.
        assert org.enabled_modules == snapshot['enabled_modules']
        assert org.active_profile_id == snapshot['active_profile_id']

    def test_preview_unknown_profile_module_raises(self):
        # Profile references a module that is not registered.
        org = _org()
        profile = _profile(modules=['core', 'ghost_module'])
        with pytest.raises(ProfileSwitchError) as exc:
            preview_profile_switch(
                organization=org,
                profile=profile,
                modules=[_SniffingModule('core')],
            )
        assert exc.value.code == 'unknown_module'

    def test_preview_is_deterministic(self):
        """Calling preview twice with the same inputs must yield the same plan."""
        org = _org(enabled_modules=['core', 'items', 'locations', 'categories'])
        profile = _profile('food_home')
        modules = [_SniffingModule(m) for m in profile.default_modules]

        first = preview_profile_switch(
            organization=org,
            profile=profile,
            modules=modules,
        )
        second = preview_profile_switch(
            organization=org,
            profile=profile,
            modules=modules,
        )
        assert first == second

    def test_preview_does_not_run_hooks(self):
        """If a module's hook is invoked during a preview, _SniffingModule
        raises. The preview must not invoke any lifecycle hook."""
        org = _org(enabled_modules=['core', 'items', 'locations', 'categories'])
        profile = _profile('food_home')
        modules = [_SniffingModule(m) for m in profile.default_modules]

        # No assertion error raised = success.
        preview_profile_switch(
            organization=org,
            profile=profile,
            modules=modules,
        )

    def test_preview_does_not_seen_or_modify_db(self):
        """The dry-run must not issue any DB write."""
        org = _org()
        profile = _profile()
        modules = [_SniffingModule(m) for m in profile.default_modules]

        # No DB session is passed to preview — if it tries to use one,
        # the test will fail with a TypeError.
        preview_profile_switch(
            organization=org,
            profile=profile,
            modules=modules,
        )
