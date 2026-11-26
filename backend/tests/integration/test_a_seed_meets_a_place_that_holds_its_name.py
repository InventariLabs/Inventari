"""What a seed does when the name it wants is held by another place.

A seeded place is written past the storage service, so the seeds ask the
sibling-name rule themselves. An insert that meets a taken name answers the
same 409, naming the place. A rename into the reader's language is optional:
the row keeps its old name and the operation that ran the seed goes on.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException
from app.i18n.service import set_current_lang
from app.models.organization import Organization
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.storage._defaults import (
    create_default_storage_locations_async,
    ensure_virtual_locations_async,
)
from app.services.token_service import get_password_hash

CONSUMED_EN = 'Consumed (Virtual)'
CONSUMED_PL = 'Zużyte (wirtualna)'
MAIN_EN = 'Main Storage'
MAIN_PL = 'Magazyn główny'


@pytest.fixture
async def seed_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Squatted Seed Org', enabled_modules=['core'])
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def seed_user(
    real_async_db_session: AsyncSession, seed_org: Organization
) -> User:
    user = User(
        email=f'squat_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Squat User',
        organization_id=seed_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def seed_types(
    real_async_db_session: AsyncSession, seed_org: Organization
) -> None:
    """The types the seeds stand their places on: a SYSTEM and a SHELF."""
    real_async_db_session.add_all(
        [
            StorageType(name='System', type_code='SYSTEM', organization_id=seed_org.id),
            StorageType(name='Shelf', type_code='SHELF', organization_id=seed_org.id),
        ]
    )
    await real_async_db_session.commit()


def _a_place(
    db: AsyncSession, organization_id, name: str, created_by, **fields
) -> StorageLocation:
    place = StorageLocation(
        organization_id=organization_id,
        name=name,
        created_by=created_by,
        **fields,
    )
    db.add(place)
    return place


def _archived() -> dict:
    return {'settings': {'archived': 'true'}}


async def _count(db: AsyncSession, organization_id) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(StorageLocation)
            .where(StorageLocation.organization_id == organization_id)
        )
        or 0
    )


@pytest.mark.asyncio
class TestASeedMeetsItsNameTaken:
    async def test_a_virtual_place_whose_name_a_place_holds_is_a_refusal(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
        seed_types: None,
    ) -> None:
        db = real_async_db_session
        _a_place(
            db,
            seed_org.id,
            CONSUMED_EN,
            seed_user.id,
            usage=LocationUsage.INTERNAL,
            **_archived(),
        )
        await db.commit()
        before = await _count(db, seed_org.id)

        with pytest.raises(ConflictException) as refused:
            await ensure_virtual_locations_async(db, seed_org.id, seed_user.id)

        assert refused.value.detail['code'] == 'STORAGE_CONFLICT'
        assert CONSUMED_EN in refused.value.detail['message']
        assert await _count(db, seed_org.id) == before

    async def test_a_virtual_row_keeps_its_name_when_the_languages_is_taken(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
        seed_types: None,
    ) -> None:
        db = real_async_db_session
        row = _a_place(
            db,
            seed_org.id,
            CONSUMED_EN,
            seed_user.id,
            usage=LocationUsage.CUSTOMER,
            settings={
                'seed': {'code': 'CONSUMED_VIRTUAL', 'name': CONSUMED_EN},
            },
        )
        _a_place(
            db,
            seed_org.id,
            CONSUMED_PL,
            seed_user.id,
            usage=LocationUsage.INTERNAL,
            **_archived(),
        )
        await db.commit()

        set_current_lang('pl')
        try:
            await ensure_virtual_locations_async(db, seed_org.id, seed_user.id)
        finally:
            set_current_lang('en')

        await db.refresh(row)
        assert row.name == CONSUMED_EN
        # Still the seeder's own name, so it joins once the other one is free.
        assert row.settings['seed']['name'] == CONSUMED_EN

    async def test_an_archived_main_storage_stays_archived(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
        seed_types: None,
    ) -> None:
        """The seed neither restores the row nor writes another in its stead."""
        db = real_async_db_session
        row = _a_place(
            db,
            seed_org.id,
            MAIN_EN,
            seed_user.id,
            settings={
                'archived': 'true',
                'seed': {'code': 'MAIN_STORAGE', 'name': MAIN_EN},
            },
        )
        await db.commit()

        created = await create_default_storage_locations_async(
            db, seed_org.id, seed_user.id
        )

        assert created == []
        await db.refresh(row)
        assert row.settings['archived'] == 'true'
        ordinary = await db.scalars(
            select(StorageLocation.name).where(
                StorageLocation.organization_id == seed_org.id,
                StorageLocation.usage == LocationUsage.INTERNAL,
            )
        )
        assert ordinary.all() == [MAIN_EN]

    async def test_the_profile_seed_row_keeps_its_name_when_the_languages_is_taken(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
        seed_types: None,
    ) -> None:
        db = real_async_db_session
        # Neither counts as the ordinary place the seed would otherwise
        # accept (they belong to a module), so the seeder reaches its
        # alignment: the row it adopts is the one with its handle, and the
        # Polish name it would join is held by another place.
        row = _a_place(
            db,
            seed_org.id,
            MAIN_EN,
            seed_user.id,
            context_tag='legacy_place',
            settings={
                'archived': 'true',
                # Untouched: it still carries the handle the seeder wrote.
                'seed': {'code': 'MAIN_STORAGE', 'name': MAIN_EN},
            },
        )
        _a_place(db, seed_org.id, MAIN_PL, seed_user.id, context_tag='legacy_place')
        await db.commit()

        set_current_lang('pl')
        try:
            await create_default_storage_locations_async(db, seed_org.id, seed_user.id)
        finally:
            set_current_lang('en')

        await db.refresh(row)
        assert row.name == MAIN_EN
        assert row.settings['seed']['name'] == MAIN_EN

    @pytest.mark.parametrize('namesake_beside_it', [True, False])
    async def test_a_nested_seeded_row_asks_about_its_own_level(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
        seed_types: None,
        namesake_beside_it: bool,
    ) -> None:
        db = real_async_db_session
        room = _a_place(
            db, seed_org.id, 'Room', seed_user.id, context_tag='legacy_place'
        )
        await db.flush()
        row = _a_place(
            db,
            seed_org.id,
            MAIN_EN,
            seed_user.id,
            parent_id=room.id,
            context_tag='legacy_place',
            settings={'seed': {'code': 'MAIN_STORAGE', 'name': MAIN_EN}},
        )
        _a_place(
            db,
            seed_org.id,
            MAIN_PL,
            seed_user.id,
            parent_id=room.id if namesake_beside_it else None,
            context_tag='legacy_place',
        )
        await db.commit()

        set_current_lang('pl')
        try:
            await create_default_storage_locations_async(db, seed_org.id, seed_user.id)
        finally:
            set_current_lang('en')

        await db.refresh(row)
        assert row.name == (MAIN_EN if namesake_beside_it else MAIN_PL)


@pytest.mark.asyncio
class TestWhatCountsAsSomewhereToPutGoods:
    async def test_an_archived_place_is_not_somewhere_to_put_goods(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
        seed_types: None,
    ) -> None:
        db = real_async_db_session
        # A profile that declares no main storage of its own: the one that
        # appears comes from finding nowhere ordinary.
        seed_org.active_profile_id = 'equipment_wms'
        _a_place(db, seed_org.id, 'Basement', seed_user.id, **_archived())
        await db.commit()

        created = await create_default_storage_locations_async(
            db, seed_org.id, seed_user.id
        )

        assert [place.name for place in created] == [MAIN_EN]


@pytest.mark.asyncio
@pytest.mark.parametrize('first_planted', [MAIN_EN, MAIN_PL])
async def test_two_rows_with_declared_names_are_adopted_by_name(
    real_async_db_session: AsyncSession,
    seed_org: Organization,
    seed_user: User,
    seed_types: None,
    first_planted: str,
) -> None:
    """The row adopted is the first by name, whatever the heap order.

    Planted in both orders: the Polish name sorts first, so it is the adopted
    row, and the English one keeps its name instead of being renamed.
    """
    db = real_async_db_session
    second = MAIN_PL if first_planted == MAIN_EN else MAIN_EN
    rows = {}
    for name in (first_planted, second):
        # Module-owned, so neither is the ordinary place that would end the
        # seed before it looks for its own row.
        rows[name] = _a_place(
            db, seed_org.id, name, seed_user.id, context_tag='legacy_place'
        )
        await db.commit()

    set_current_lang('de')
    try:
        created = await create_default_storage_locations_async(
            db, seed_org.id, seed_user.id
        )
    finally:
        set_current_lang('en')

    assert created == []
    for name, row in rows.items():
        await db.refresh(row)
        assert row.name == name
