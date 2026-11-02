"""Integration tests for the insert-only/no-commit seed contract.

The profile switch must be able to seed a target profile without overwriting the
user's customisations (renamed storage types, customised icons, etc.)
and without performing its own commit so the switch can be atomic.

The existing tests in ``test_seed_data.py`` lock the *current* behaviour
(seeders update existing rows and commit). This module locks the new
contracts introduced for the profile switch:

* ``insert_only=True`` — existing rows stay untouched; missing rows are
  inserted.
* ``commit=False`` — the seeder flushes but does not commit, so the
  caller controls transaction boundaries.
* Category lookup uses stable ``code`` (not ``name``) so a renamed
  category is not duplicated.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.storage_type import StorageType
from app.seed_profiles._food_home_categories import seed_food_categories
from app.seed_profiles._food_home_storage_types import seed_food_storage_types
from app.seed_profiles.base import seed_neutral_storage_types
from app.seed_profiles.equipment_wms import seed_equipment_storage_types


@pytest.fixture
async def seeded_org(real_async_db_session, async_test_household):
    """An organization whose storage types are committed.

    Storage types have an owner since, so they arrive with the
       organization rather than with the session snapshot. The commit keeps the
       rollback semantics these tests assert: a rollback in the test body must
       restore the seeded row, not remove it along with its organization.
    """
    await real_async_db_session.commit()
    return async_test_household


@pytest.mark.integration
@pytest.mark.asyncio
class TestInsertOnlySeedStorageTypes:
    """insert_only=True must preserve user customisations on storage types."""

    async def test_neutral_storage_type_custom_name_is_preserved(
        self, real_async_db_session: AsyncSession, seeded_org
    ):
        org_id = seeded_org.id
        shelf = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'SHELF',
                StorageType.organization_id == org_id,
            )
        )
        assert shelf is not None
        shelf.name = 'My Custom Shelf Name'
        shelf.icon = 'Star'
        await real_async_db_session.flush()

        await real_async_db_session.run_sync(
            lambda s: seed_neutral_storage_types(
                s, organization_id=org_id, insert_only=True
            )
        )

        refreshed = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'SHELF',
                StorageType.organization_id == org_id,
            )
        )
        assert refreshed.name == 'My Custom Shelf Name'
        assert refreshed.icon == 'Star'

    async def test_food_storage_type_custom_icon_is_preserved(
        self, real_async_db_session: AsyncSession, seeded_org
    ):
        org_id = seeded_org.id
        # Isolate from other tests' committed storage-type state: the
        # real_async_db_session fixture deliberately does NOT truncate (it
        # relies on interleaved sync tests doing that), so under xdist a
        # leftover row can make this test's seed no-op into a flake.
        from sqlalchemy import text

        await real_async_db_session.execute(text('TRUNCATE storage_types CASCADE'))
        await real_async_db_session.commit()
        await real_async_db_session.run_sync(
            lambda s: seed_food_storage_types(
                s, organization_id=org_id, insert_only=True
            )
        )

        freezer = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'FREEZER',
                StorageType.organization_id == org_id,
            )
        )
        assert freezer is not None
        freezer.icon = 'CustomFreezerIcon'
        freezer.default_settings = {'check_expiry': False, 'custom': True}
        await real_async_db_session.flush()

        await real_async_db_session.run_sync(
            lambda s: seed_food_storage_types(
                s, organization_id=org_id, insert_only=True
            )
        )

        refreshed = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'FREEZER',
                StorageType.organization_id == org_id,
            )
        )
        assert refreshed.icon == 'CustomFreezerIcon'
        assert refreshed.default_settings == {
            'check_expiry': False,
            'custom': True,
        }

    async def test_equipment_storage_type_custom_settings_are_preserved(
        self, real_async_db_session: AsyncSession, seeded_org
    ):
        org_id = seeded_org.id
        # Default session fixture only seeds neutral + food storage types.
        await real_async_db_session.run_sync(
            lambda s: seed_equipment_storage_types(s, organization_id=org_id)
        )
        room = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'TOOL_ROOM',
                StorageType.organization_id == org_id,
            )
        )
        assert room is not None
        room.name = 'My Tool Room'
        room.default_settings = {'check_expiry': True, 'custom': 'value'}
        await real_async_db_session.flush()

        await real_async_db_session.run_sync(
            lambda s: seed_equipment_storage_types(
                s, organization_id=org_id, insert_only=True
            )
        )

        refreshed = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'TOOL_ROOM',
                StorageType.organization_id == org_id,
            )
        )
        assert refreshed.name == 'My Tool Room'
        assert refreshed.default_settings == {
            'check_expiry': True,
            'custom': 'value',
        }

    async def test_missing_storage_type_is_inserted_in_insert_only_mode(
        self, real_async_db_session: AsyncSession, seeded_org
    ):
        org_id = seeded_org.id
        # Delete a system storage type, then run insert_only seeder.
        await real_async_db_session.execute(
            StorageType.__table__.delete().where(
                StorageType.type_code == 'STORAGE_ROOM',
                StorageType.organization_id == org_id,
            )
        )
        await real_async_db_session.flush()

        await real_async_db_session.run_sync(
            lambda s: seed_neutral_storage_types(
                s, organization_id=org_id, insert_only=True
            )
        )

        restored = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'STORAGE_ROOM',
                StorageType.organization_id == org_id,
            )
        )
        assert restored is not None
        # Seeder defaults were applied.
        assert restored.name == 'Storage Room'
        assert restored.is_system is True


@pytest.mark.integration
@pytest.mark.asyncio
class TestInsertOnlySeedCategories:
    """insert_only=True must preserve user customisations on categories."""

    async def test_seeded_fields_carry_the_system_flag(
        self, real_async_db_session: AsyncSession
    ):
        """The profile's field definitions are platform copy: the seed
        marks them is_system so the form can resolve their labels in the
        reader's language, while a field the user writes themselves can
        never carry the flag (the write path strips it)."""
        cat = await real_async_db_session.scalar(
            select(Category).where(Category.code == 'pork')
        )
        assert cat is not None
        fields = {f['key']: f for f in cat.field_definitions}
        assert fields['freeze_date'].get('is_system') is True
        assert fields['cut_type'].get('is_system') is True

    async def test_category_custom_icon_is_preserved(
        self, real_async_db_session: AsyncSession
    ):
        cat = await real_async_db_session.scalar(
            select(Category).where(Category.code == 'pork')
        )
        assert cat is not None
        cat.icon = 'CustomPorkIcon'
        cat.sort_order = 999
        await real_async_db_session.flush()

        await real_async_db_session.run_sync(
            lambda s: seed_food_categories(s, insert_only=True)
        )

        refreshed = await real_async_db_session.scalar(
            select(Category).where(Category.code == 'pork')
        )
        assert refreshed.icon == 'CustomPorkIcon'
        assert refreshed.sort_order == 999

    async def test_renamed_category_is_not_duplicated(
        self, real_async_db_session: AsyncSession
    ):
        """Lookup by code (not name) — renaming a category must not cause
        a duplicate row on the next seed run."""
        cat = await real_async_db_session.scalar(
            select(Category).where(Category.code == 'pork')
        )
        assert cat is not None
        cat.name = 'Pork (renamed by user)'
        await real_async_db_session.flush()

        before_count = await real_async_db_session.scalar(
            select(func.count(Category.id)).where(Category.code == 'pork')
        )

        await real_async_db_session.run_sync(
            lambda s: seed_food_categories(s, insert_only=True)
        )

        after_count = await real_async_db_session.scalar(
            select(func.count(Category.id)).where(Category.code == 'pork')
        )
        assert after_count == before_count, (
            'renamed category was duplicated by insert-only seed'
        )
        # User's custom name is preserved.
        refreshed = await real_async_db_session.scalar(
            select(Category).where(Category.code == 'pork')
        )
        assert refreshed.name == 'Pork (renamed by user)'

    async def test_missing_category_is_inserted_in_insert_only_mode(
        self, real_async_db_session: AsyncSession
    ):
        await real_async_db_session.execute(
            Category.__table__.delete().where(Category.code == 'dairy')
        )
        await real_async_db_session.flush()

        await real_async_db_session.run_sync(
            lambda s: seed_food_categories(s, insert_only=True)
        )

        restored = await real_async_db_session.scalar(
            select(Category).where(Category.code == 'dairy')
        )
        assert restored is not None
        # Default seed values were applied.
        assert restored.is_active is True


@pytest.mark.integration
@pytest.mark.asyncio
class TestCommitFalseSeed:
    """commit=False flushes but does not commit, so the caller can roll back."""

    async def test_equipment_storage_types_commit_false_does_not_persist(
        self, real_async_db_session: AsyncSession, seeded_org
    ):
        org_id = seeded_org.id
        """commit=False must not persist newly inserted rows after rollback.

        Equipment storage types are NOT seeded by the default session
        setup, so the commit semantics are unambiguous here — provided
        a previous test hasn't already seeded them. We work defensively
        by deleting the row first and tracking the original ID.
        """
        original = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'TOOL_ROOM',
                StorageType.organization_id == org_id,
            )
        )
        original_id = original.id if original else None

        await real_async_db_session.execute(
            StorageType.__table__.delete().where(
                StorageType.type_code == 'TOOL_ROOM',
                StorageType.organization_id == org_id,
            )
        )
        await real_async_db_session.flush()

        await real_async_db_session.run_sync(
            lambda s: seed_equipment_storage_types(
                s, organization_id=org_id, commit=False
            )
        )

        # Inside the session, the row is visible (with a new id).
        flushed = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'TOOL_ROOM',
                StorageType.organization_id == org_id,
            )
        )
        assert flushed is not None
        if original_id is not None:
            assert flushed.id != original_id, (
                'seeder must have inserted a new row, not restored the original'
            )

        # Roll back — the seeder's insert must be undone.
        await real_async_db_session.rollback()

        after_rollback = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'TOOL_ROOM',
                StorageType.organization_id == org_id,
            )
        )
        if original_id is not None:
            assert after_rollback is not None
            assert after_rollback.id == original_id, (
                'rollback must restore the original row, not the seeder insert'
            )
        else:
            assert after_rollback is None

    async def test_neutral_storage_types_commit_false_does_not_persist(
        self, real_async_db_session: AsyncSession, seeded_org
    ):
        org_id = seeded_org.id
        """Removing an existing row and seeding with commit=False must
        not leave the row in the DB after the session rolls back."""
        # Capture the original ID so we can detect "new row inserted by
        # the seeder" vs "original row restored by rollback".
        original = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'STORAGE_ROOM',
                StorageType.organization_id == org_id,
            )
        )
        assert original is not None
        original_id = original.id

        await real_async_db_session.execute(
            StorageType.__table__.delete().where(
                StorageType.type_code == 'STORAGE_ROOM',
                StorageType.organization_id == org_id,
            )
        )
        await real_async_db_session.flush()

        await real_async_db_session.run_sync(
            lambda s: seed_neutral_storage_types(
                s, organization_id=org_id, commit=False
            )
        )

        # Inside the session, the row is visible (with a new id).
        visible = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'STORAGE_ROOM',
                StorageType.organization_id == org_id,
            )
        )
        assert visible is not None
        assert visible.id != original_id, (
            'seeder must have inserted a new row, not restored the original'
        )

        # Roll back — the seeder's insert must be undone.
        await real_async_db_session.rollback()

        after_rollback = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'STORAGE_ROOM',
                StorageType.organization_id == org_id,
            )
        )
        assert after_rollback is not None
        assert after_rollback.id == original_id, (
            'rollback must restore the original row, not the seeder insert'
        )

    async def test_food_categories_commit_false_does_not_persist(
        self, real_async_db_session: AsyncSession
    ):
        # Same id-tracking pattern as the storage type test above.
        original = await real_async_db_session.scalar(
            select(Category).where(Category.code == 'dairy')
        )
        assert original is not None
        original_id = original.id

        await real_async_db_session.execute(
            Category.__table__.delete().where(Category.code == 'dairy')
        )
        await real_async_db_session.flush()

        await real_async_db_session.run_sync(
            lambda s: seed_food_categories(s, commit=False)
        )

        visible = await real_async_db_session.scalar(
            select(Category).where(Category.code == 'dairy')
        )
        assert visible is not None
        assert visible.id != original_id

        await real_async_db_session.rollback()

        after_rollback = await real_async_db_session.scalar(
            select(Category).where(Category.code == 'dairy')
        )
        assert after_rollback is not None
        assert after_rollback.id == original_id


@pytest.mark.integration
@pytest.mark.asyncio
class TestDefaultBehaviorPreserved:
    """When called with no arguments, the seeders keep their old behaviour."""

    async def test_default_mode_keeps_a_name_the_organization_changed(
        self, real_async_db_session: AsyncSession, seeded_org
    ):
        """A name that is not the literal the seeder wrote is the user's.

        This used to assert the opposite — the profile seeder overwrote
        ``existing.name`` on every call while a module's declared types left a
        renamed row alone. Two seeders of one table disagreeing about who owns
        a name is the defect, not a default: a type's name is editable and
        printed, so a row that says something else is the organization's. What
        a later seed may still bring into line is a row still carrying the
        literal it was seeded with (see the storage-type language tests).
        """
        org_id = seeded_org.id
        shelf = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'SHELF',
                StorageType.organization_id == org_id,
            )
        )
        assert shelf is not None
        shelf.name = 'Old Name'
        await real_async_db_session.flush()

        await real_async_db_session.run_sync(
            lambda s: seed_neutral_storage_types(s, organization_id=org_id)
        )

        refreshed = await real_async_db_session.scalar(
            select(StorageType).where(
                StorageType.type_code == 'SHELF',
                StorageType.organization_id == org_id,
            )
        )
        assert refreshed.name == 'Old Name'
