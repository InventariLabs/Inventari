"""A seed that meets a place already holding its name refuses, not 500s.

Every seeded place is written by a path that never went through the storage
service, so it never asked the sibling-name rule — and since a parentless
name is unique, a hand-made (often archived) place holding the seed's name
met the index raw. The seeds now ask the same rule and answer the same 409,
naming the place, whether they insert or rename their row.
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

    async def test_a_virtual_row_joining_the_language_meets_a_taken_name(
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
            with pytest.raises(ConflictException) as refused:
                await ensure_virtual_locations_async(db, seed_org.id, seed_user.id)
        finally:
            set_current_lang('en')

        assert refused.value.detail['code'] == 'STORAGE_CONFLICT'
        assert CONSUMED_PL in refused.value.detail['message']

    async def test_the_profile_seed_renaming_its_row_meets_a_taken_name(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
        seed_types: None,
    ) -> None:
        db = real_async_db_session
        # Neither counts as the ordinary place the seed would otherwise
        # accept (they belong to a module), so the seeder reaches its
        # alignment: the row it adopts is the English literal, and the Polish
        # name it would join is held by another place.
        _a_place(
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
            with pytest.raises(ConflictException) as refused:
                await create_default_storage_locations_async(
                    db, seed_org.id, seed_user.id
                )
        finally:
            set_current_lang('en')

        assert refused.value.detail['code'] == 'STORAGE_CONFLICT'
        assert MAIN_PL in refused.value.detail['message']
