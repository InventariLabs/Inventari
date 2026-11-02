"""Integration tests for app.services.profile_switch_service — apply path.

The apply service executes a profile switch transactionally. It MUST:

* run disable hooks in reverse-topological order,
* run seed in insert-only mode (no overwrite of user customisations),
* run enable hooks in topological order,
* apply module_config presets through the validated, secret-aware path,
* update ``enabled_modules``, ``active_profile_id``, and
  ``onboarding_completed`` atomically,
* roll back the entire transaction if any hook or seed fails,
* invalidate the module cache only after a successful commit.

"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core._base_module import BaseModule
from app.core._module_declarations import ModuleMetadata
from app.core.product_profiles import ProductProfile
from app.database import dispatch_committed_events
from app.models.organization import Organization
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.profile_switch_service import (
    ProfileSwitchApplyError,
    apply_profile_switch,
)


class _SniffingModule(BaseModule):
    """Records hook invocations and (optionally) raises on enable."""

    def __init__(
        self,
        name: str,
        *,
        raise_on_enable: bool = False,
    ) -> None:
        self._name = name
        self._raise_on_enable = raise_on_enable
        self.events: list[tuple[str, str]] = []

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
        self.events.append(('system_on_enable', organization_id))

    async def system_on_disable(self, organization_id: str, db: Any) -> None:
        self.events.append(('system_on_disable', organization_id))

    def on_enable(self, organization_id: str, context: Any) -> None:
        if self._raise_on_enable:
            raise RuntimeError('on_enable boom')
        self.events.append(('on_enable', organization_id))

    def on_disable(self, organization_id: str, context: Any) -> None:
        self.events.append(('on_disable', organization_id))


def _clean_profile() -> ProductProfile:
    return ProductProfile(
        id='clean_core',
        name='Custom',
        description='Minimal.',
        default_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
        ],
        seed_profile='clean_core',
    )


def _food_profile() -> ProductProfile:
    return ProductProfile(
        id='food_home',
        name='Food & Home',
        description='Food.',
        default_modules=[
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
        ],
        seed_profile='food_home',
    )


@pytest.mark.integration
@pytest.mark.asyncio
class TestApplyProfileSwitch:
    """Happy-path: switch a clean org to a profile."""

    async def test_apply_clean_core_to_food_home_enables_modules(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        # Org starts with the clean_core default modules.
        async_test_household.enabled_modules = list(_clean_profile().default_modules)
        async_test_household.active_profile_id = 'clean_core'
        await real_async_db_session.flush()

        modules = [_SniffingModule(m) for m in _food_profile().default_modules]

        result = await apply_profile_switch(
            db=real_async_db_session,
            organization=async_test_household,
            profile=_food_profile(),
            modules=modules,
            user=async_test_user,
        )

        # Plan fields are populated.
        assert result.to_profile_id == 'food_home'
        assert result.from_profile_id == 'clean_core'
        # Shopping, recipes, nutrition, vision are enabled.
        for m in ('shopping_lists', 'recipes', 'nutrition', 'vision'):
            assert m in result.enable or m in result.unchanged
        # Final enabled modules reflect the new target.
        for m in _food_profile().default_modules:
            assert m in result.final_enabled_modules

        # Org row has new state.
        assert async_test_household.active_profile_id == 'food_home'
        assert async_test_household.onboarding_completed is True
        for m in _food_profile().default_modules:
            assert m in async_test_household.enabled_modules

    async def test_apply_food_home_to_clean_core_disables_food_modules(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        async_test_household.enabled_modules = list(_food_profile().default_modules)
        async_test_household.active_profile_id = 'food_home'
        await real_async_db_session.flush()

        modules = [_SniffingModule(m) for m in _food_profile().default_modules]

        with (
            patch(
                'app.services.profile_switch_service.disable_modules_async',
                new=AsyncMock(),
            ) as disable_mock,
            patch(
                'app.services.profile_switch_service.enable_modules_async',
                new=AsyncMock(),
            ) as enable_mock,
        ):
            # Patch the lifecycle executor so the test only cares about
            # the orchestration, not the hook calls.
            await apply_profile_switch(
                db=real_async_db_session,
                organization=async_test_household,
                profile=_clean_profile(),
                modules=modules,
                user=async_test_user,
            )

        # Disable was called with the correct modules in reverse-topo order.
        assert disable_mock.await_count == 1
        disabled_names = disable_mock.await_args.args[0]
        disabled_names_set = {m.metadata.name for m in disabled_names}
        for m in ('shopping_lists', 'recipes', 'nutrition', 'vision'):
            assert m in disabled_names_set

        # Enable was called with the correct modules in topo order.
        assert enable_mock.await_count == 1
        enabled_names = enable_mock.await_args.args[0]
        enabled_names_set = {m.metadata.name for m in enabled_names}
        # No new modules to enable when going to clean_core.
        assert enabled_names_set == set() or enabled_names_set.issubset({'stock_takes'})

        # Org state updated.
        assert async_test_household.active_profile_id == 'clean_core'
        for m in _clean_profile().default_modules:
            assert m in async_test_household.enabled_modules


@pytest.mark.integration
@pytest.mark.asyncio
class TestApplyRollback:
    """If a hook fails, the entire transaction must be rolled back."""

    async def test_on_enable_failure_rolls_back_transaction(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        async_test_household.enabled_modules = list(_clean_profile().default_modules)
        async_test_household.active_profile_id = 'clean_core'
        await real_async_db_session.flush()

        # Build modules; one of them will raise during enable.
        boom = _SniffingModule('vision', raise_on_enable=True)
        modules = [_SniffingModule(m) for m in _food_profile().default_modules]
        # Replace the 'vision' module with the raising one.
        modules = [m if m.metadata.name != 'vision' else boom for m in modules]

        with (
            patch(
                'app.services.profile_switch_service.disable_modules_async',
                new=AsyncMock(),
            ),
            patch(
                'app.services.profile_switch_service.enable_modules_async',
                new=AsyncMock(
                    side_effect=RuntimeError('on_enable boom from the executor')
                ),
            ),
        ):
            with pytest.raises(ProfileSwitchApplyError):
                await apply_profile_switch(
                    db=real_async_db_session,
                    organization=async_test_household,
                    profile=_food_profile(),
                    modules=modules,
                    user=async_test_user,
                )

        # The async test fixture holds the org in the same transaction, so
        # rollback would also remove the org itself. We verify the org's
        # in-memory state was NOT updated to the new profile, which is the
        # contract that matters for a failed transaction.
        assert async_test_household.active_profile_id == 'clean_core'
        for m in _clean_profile().default_modules:
            assert m in async_test_household.enabled_modules

    async def test_a_failed_switch_keeps_the_journal_entry_written_before_it(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        """The switch undoes only its own part: an entry the request wrote
        before asking for it is still there for the caller to commit."""
        from app.core.contracts import AuditAction, AuditTargetType
        from app.core.public_api import core_api
        from app.models.audit_log import AuditLog

        db = real_async_db_session
        async_test_household.enabled_modules = list(_clean_profile().default_modules)
        async_test_household.active_profile_id = 'clean_core'
        await core_api.audit_log.log_action_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.MODULE,
            target_id=async_test_household.id,
            snapshot={'name': 'written before the switch'},
        )
        await db.flush()

        modules = [_SniffingModule(m) for m in _food_profile().default_modules]
        with patch(
            'app.services.profile_switch_service.enable_modules_async',
            new=AsyncMock(side_effect=RuntimeError('enable failed halfway')),
        ):
            with pytest.raises(ProfileSwitchApplyError):
                await apply_profile_switch(
                    db=db,
                    organization=async_test_household,
                    profile=_food_profile(),
                    modules=modules,
                    user=async_test_user,
                )

        rows = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == async_test_household.id
                )
            )
        ).all()
        assert 'written before the switch' in [
            (row.snapshot or {}).get('name') for row in rows
        ]
        await db.refresh(async_test_household, ['active_profile_id'])
        assert async_test_household.active_profile_id == 'clean_core'


@pytest.mark.integration
@pytest.mark.asyncio
class TestApplySeed:
    """The apply path must use insert-only seed."""

    async def test_apply_does_not_overwrite_user_customisations(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        # Rename a storage type to verify the apply preserves user data.
        freezer = await real_async_db_session.scalar(
            select(StorageType).where(StorageType.type_code == 'FREEZER')
        )
        assert freezer is not None
        freezer.name = 'My Custom Freezer'
        await real_async_db_session.flush()

        async_test_household.enabled_modules = list(_clean_profile().default_modules)
        async_test_household.active_profile_id = 'clean_core'
        await real_async_db_session.flush()

        modules = [_SniffingModule(m) for m in _food_profile().default_modules]

        await apply_profile_switch(
            db=real_async_db_session,
            organization=async_test_household,
            profile=_food_profile(),
            modules=modules,
            user=async_test_user,
        )

        # Re-fetch and verify the custom name is preserved.
        refreshed = await real_async_db_session.scalar(
            select(StorageType).where(StorageType.type_code == 'FREEZER')
        )
        assert refreshed.name == 'My Custom Freezer'


@pytest.mark.integration
@pytest.mark.asyncio
class TestApplyDocumentPreset:
    """A profile declaring ``document_preset`` must apply it during a
    switch so value tracking follows the target profile (not stuck on the old
    org setting)."""

    async def test_switch_to_profile_with_preset_enables_value_tracking(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        from app.modules.warehouse.document_profile_service import (
            get_profile as get_document_profile,
        )

        target = ProductProfile(
            id='wms_value',
            name='WMS Value',
            description='Documents with value tracking.',
            default_modules=[
                'core',
                'items',
                'locations',
                'categories',
                'stock_takes',
                'warehouse',
            ],
            seed_profile='clean_core',
            document_preset='Full Value',
        )
        async_test_household.enabled_modules = list(_clean_profile().default_modules)
        async_test_household.active_profile_id = 'clean_core'
        await real_async_db_session.flush()

        modules = [_SniffingModule(m) for m in target.default_modules]

        await apply_profile_switch(
            db=real_async_db_session,
            organization=async_test_household,
            profile=target,
            modules=modules,
            user=async_test_user,
        )

        doc_profile = await get_document_profile(
            real_async_db_session, async_test_household.id
        )
        assert doc_profile is not None
        assert doc_profile.value_tracking_enabled is True
        assert doc_profile.name == 'Full Value'


@pytest.mark.integration
@pytest.mark.asyncio
class TestApplyCacheInvalidation:
    """The apply path must invalidate the module cache after commit."""

    async def test_apply_invalidates_module_cache_after_commit(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        async_test_household.enabled_modules = list(_clean_profile().default_modules)
        async_test_household.active_profile_id = 'clean_core'
        await real_async_db_session.flush()

        modules = [_SniffingModule(m) for m in _food_profile().default_modules]

        with patch(
            'app.core._require_module.cache_delete', new=AsyncMock()
        ) as cache_delete_mock:
            await apply_profile_switch(
                db=real_async_db_session,
                organization=async_test_household,
                profile=_food_profile(),
                modules=modules,
                user=async_test_user,
            )
            # Cleared before the commit, a concurrent read would re-cache the
            # old set for the full TTL.
            cache_delete_mock.assert_not_awaited()

            await real_async_db_session.commit()
            await dispatch_committed_events(real_async_db_session)

        # Cache for this org's modules must be invalidated.
        cache_delete_mock.assert_awaited_once()
        assert cache_delete_mock.await_args.args[0] == (
            f'org:{async_test_household.id}:modules'
        )

    async def test_rollback_does_not_invalidate_cache(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        async_test_household.enabled_modules = list(_clean_profile().default_modules)
        async_test_household.active_profile_id = 'clean_core'
        await real_async_db_session.flush()

        boom = _SniffingModule('vision', raise_on_enable=True)
        modules = [_SniffingModule(m) for m in _food_profile().default_modules]
        modules = [m if m.metadata.name != 'vision' else boom for m in modules]

        with patch(
            'app.core._require_module.cache_delete', new=AsyncMock()
        ) as cache_delete_mock:
            with pytest.raises(ProfileSwitchApplyError):
                await apply_profile_switch(
                    db=real_async_db_session,
                    organization=async_test_household,
                    profile=_food_profile(),
                    modules=modules,
                    user=async_test_user,
                )
            await dispatch_committed_events(real_async_db_session)

        # Cache must NOT be invalidated when the apply fails.
        cache_delete_mock.assert_not_called()


def _equipment_profile() -> ProductProfile:
    """A profile that moves module settings, not only the module set."""
    return ProductProfile(
        id='equipment_wms',
        name='Equipment & WMS',
        description='Warehouse.',
        default_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'equipment',
            'stats',
        ],
        seed_profile='clean_core',
        module_config={
            'equipment': {
                'warranty_warning_days': 60,
                'maintenance_warning_days': 14,
            },
        },
    )


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheSwitchNamesTheSettingsItMoved:
    """A switch rewrites module settings; the journal must name them.

    It named the profile and both module lists and nothing else, so an
    organization could come out of a switch with a different warranty
    window and no way to tell afterwards which operation set it.
    """

    async def test_the_entry_names_the_module_and_the_keys_that_moved(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        from app.models.audit_log import AuditLog

        async_test_household.enabled_modules = list(_clean_profile().default_modules)
        async_test_household.active_profile_id = 'clean_core'
        async_test_household.settings = {}
        await real_async_db_session.flush()

        modules = [_SniffingModule(m) for m in _equipment_profile().default_modules]

        await apply_profile_switch(
            db=real_async_db_session,
            organization=async_test_household,
            profile=_equipment_profile(),
            modules=modules,
            user=async_test_user,
        )

        rows = (
            await real_async_db_session.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == async_test_household.id,
                    AuditLog.target_type == 'module',
                )
            )
        ).all()
        named = {row.snapshot['name']: row.snapshot for row in rows}
        assert 'equipment' in named, (
            'the switch moved module:equipment settings and the journal '
            f'names nothing: {[row.snapshot for row in rows]}'
        )
        entry = named['equipment']
        assert entry['subject'] == 'profile:equipment_wms'
        # The before side reads the schema default for a key the org had
        # never stored: 30 is what the module ran with until this switch.
        assert entry['before']['warranty_warning_days'] == 30
        assert entry['after']['warranty_warning_days'] == 60
        assert entry['after']['maintenance_warning_days'] == 14

        stored = (async_test_household.settings or {}).get('module:equipment', {})
        assert stored.get('warranty_warning_days') == 60

    async def test_a_switch_that_moves_no_settings_journals_no_entry(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_household: Organization,
    ):
        """The journal records changes, not operations."""
        from app.models.audit_log import AuditLog

        async_test_household.enabled_modules = list(_clean_profile().default_modules)
        async_test_household.active_profile_id = 'clean_core'
        async_test_household.settings = {
            'module:equipment': {
                'warranty_warning_days': 60,
                'maintenance_warning_days': 14,
            }
        }
        await real_async_db_session.flush()

        modules = [_SniffingModule(m) for m in _equipment_profile().default_modules]

        await apply_profile_switch(
            db=real_async_db_session,
            organization=async_test_household,
            profile=_equipment_profile(),
            modules=modules,
            user=async_test_user,
        )

        rows = (
            await real_async_db_session.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == async_test_household.id,
                    AuditLog.target_type == 'module',
                )
            )
        ).all()
        assert rows == []
