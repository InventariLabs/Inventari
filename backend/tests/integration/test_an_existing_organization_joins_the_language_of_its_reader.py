"""An organization that already exists joins the reader's language too.

The seeders write a type's name in the language the seed runs in — but only
the fresh-onboarding path ran them that way. The profile-switch path seeded
with ``insert_only=True``, which froze every existing row, so an organization
seeded before the language was chosen had no route to Polish names: its rows
held "Freezer" while its reader read "Zamrażarka", and re-picking the profile
left them exactly as they were.

A row still bearing the literal the seeder wrote is not a customisation —
that rule already guarded the non-insert-only path. These tests pin it across
both modes: the name joins the reader, a renamed row stays the organization's,
and everything else about an insert-only row stays frozen.
"""

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n.service import set_current_lang
from app.models.organization import Organization
from app.models.storage_type import StorageType
from app.seed_profiles._food_home_storage_types import seed_food_storage_types


@pytest.fixture
async def seeded_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Switch Language Org', enabled_modules=['core'])
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


async def _english_freezer(
    db: AsyncSession, organization_id, name: str = 'Freezer'
) -> StorageType:
    """A FREEZER row as the install-day seeder wrote it, with one value
    deliberately different from the seed in every refreshed column: if the
    insert-only run refreshed anything beyond the name, this row is where it
    shows — and each column names itself."""
    row = StorageType(
        name=name,
        type_code='FREEZER',
        behavior_mode='STOCK',
        icon='Package',
        is_system=True,
        default_settings={'check_expiry': False},
        context_schema=['quantity'],
        organization_id=organization_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _freezer_name(db: AsyncSession, organization_id) -> str | None:
    row = (
        await db.scalars(
            select(StorageType).where(
                StorageType.type_code == 'FREEZER',
                StorageType.organization_id == organization_id,
            )
        )
    ).first()
    return row.name if row else None


@pytest.mark.integration
class TestInsertOnlySeedRepairsRowsNobodyRenamed:
    async def test_insert_only_seed_localizes_the_row_still_bearing_the_literal(
        self, real_async_db_session: AsyncSession, seeded_org: Organization
    ) -> None:
        await _english_freezer(real_async_db_session, seeded_org.id)

        set_current_lang('pl')
        try:
            await real_async_db_session.run_sync(
                lambda session: seed_food_storage_types(
                    session,
                    organization_id=seeded_org.id,
                    insert_only=True,
                    commit=False,
                )
            )
            await real_async_db_session.flush()
        finally:
            set_current_lang('en')

        row = (
            await real_async_db_session.scalars(
                select(StorageType).where(
                    StorageType.type_code == 'FREEZER',
                    StorageType.organization_id == seeded_org.id,
                )
            )
        ).first()
        assert row is not None
        assert row.name == 'Zamrażarka', (
            'a profile switch is the route an already-seeded organization '
            'takes to the reader’s language'
        )
        # insert_only keeps its promise about everything that is not the
        # seeded literal, column by column: every value the row carried
        # deliberately off-seed survives the switch.
        assert row.behavior_mode == 'STOCK'
        assert row.icon == 'Package'
        assert row.default_settings == {'check_expiry': False}
        assert row.context_schema == ['quantity']

    async def test_insert_only_seed_leaves_a_renamed_row_alone(
        self, real_async_db_session: AsyncSession, seeded_org: Organization
    ) -> None:
        await _english_freezer(real_async_db_session, seeded_org.id, name='Chłodnia')

        set_current_lang('pl')
        try:
            await real_async_db_session.run_sync(
                lambda session: seed_food_storage_types(
                    session,
                    organization_id=seeded_org.id,
                    insert_only=True,
                    commit=False,
                )
            )
            await real_async_db_session.flush()
        finally:
            set_current_lang('en')

        assert await _freezer_name(real_async_db_session, seeded_org.id) == 'Chłodnia'


@pytest.mark.integration
class TestTheSwitchBringsTheLanguageWithIt:
    async def test_switching_profile_in_polish_localizes_the_preseeded_row(
        self, client, auth_headers, db_session, test_household
    ) -> None:
        """The reported case: an organization seeded in English before
        the fix, whose reader now reads Polish, re-picks the profile — and
        the rows nobody renamed come back in Polish."""
        test_household.active_profile_id = 'clean_core'
        test_household.enabled_modules = [
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
        ]
        db_session.commit()

        # The API harness carries a sync session: seed and read with it.
        # The fixture org may already hold a FREEZER row from its own setup —
        # adapt THAT row to the install-day state instead of duplicating it,
        # so the assertion reads the row the seed actually repaired.
        row = db_session.scalars(
            select(StorageType).where(
                StorageType.type_code == 'FREEZER',
                StorageType.organization_id == test_household.id,
            )
        ).first()
        if row is None:
            row = StorageType(
                type_code='FREEZER',
                icon='Snowflake',
                is_system=True,
                default_settings={'check_expiry': True},
                context_schema=[],
                organization_id=test_household.id,
            )
            db_session.add(row)
        row.name = 'Freezer'
        # Every refreshed column carries a deliberately off-seed value, so
        # the survival asserts below each name the column that kept it.
        row.behavior_mode = 'STOCK'
        row.icon = 'Package'
        row.default_settings = {'check_expiry': False}
        row.context_schema = ['quantity']
        db_session.commit()

        response = client.post(
            '/api/v1/onboarding/switch-profile',
            json={'profile_id': 'food_home', 'dry_run': False},
            headers={**auth_headers, 'Accept-Language': 'pl'},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['applied'] is True

        db_session.expire_all()
        db_session.refresh(row)
        assert row.name == 'Zamrażarka'
        # insert_only keeps its promise beyond the name, column by column:
        # the deliberately off-seed values the row carried survive the
        # switch.
        assert row.behavior_mode == 'STOCK'
        assert row.icon == 'Package'
        assert row.default_settings == {'check_expiry': False}
        assert row.context_schema == ['quantity']
