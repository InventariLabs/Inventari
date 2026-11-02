"""A storage type is named in the language its seed ran in.

A type's name is data: it stands in the storage picker, on the storage's card
and in every exported row. Every seeder wrote it in English whichever language
the organization was being set up in, so a Polish organization met its first
storage screen — the wizard's third step — with twelve English options beside
a Polish "Brak (wyspecjalizowane pola)", indistinguishable from a label the
user had typed themselves. Its sibling, the location, had been fixed already,
which is why the same room answered to "Server Room" as a type and
"Serwerownia" as a place.

Both seeders now write the name in the language the seeding runs in, and an
organization seeded before that joins the language of the session that seeds
it again — but only while the row still carries the literal the seeder wrote.
A name the organization changed is the organization's, and the two seeders
used to disagree about exactly that: a module declaration left a renamed row
alone while the profile seeder overwrote it on every switch.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n.service import set_current_lang
from app.models.organization import Organization
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.equipment.module import EquipmentModule
from app.seed_profiles._food_home_storage_types import seed_food_storage_types
from app.seed_profiles.base import seed_neutral_storage_types
from app.seed_profiles.equipment_wms import seed_equipment_storage_types
from app.services.token_service import get_password_hash

#: What each seeded type is called in the language the seeder writes.
#: ``SYSTEM`` is absent on purpose: "System" is the Polish word too, and it is
#: the one seeded name this repair is right to leave alone.
POLISH_NAMES = {
    'SHELF': 'Półka / szafa',
    'STORAGE_ROOM': 'Pomieszczenie magazynowe',
    'FREEZER': 'Zamrażarka',
    'FRIDGE': 'Lodówka',
    'PANTRY': 'Spiżarnia',
    'MEDICINE_CABINET': 'Apteczka',
    'TOOL_ROOM': 'Narzędziownia',
    'MAINTENANCE_BAY': 'Stanowisko serwisowe',
    'SERVER_ROOM': 'Serwerownia',
    'IT_STORAGE': 'Magazyn IT',
}

ENGLISH_NAMES = {
    'SHELF': 'Shelf / Cabinet',
    'STORAGE_ROOM': 'Storage Room',
    'SYSTEM': 'System',
    'FREEZER': 'Freezer',
    'FRIDGE': 'Fridge',
    'PANTRY': 'Pantry',
    'MEDICINE_CABINET': 'Medicine Cabinet',
    'TOOL_ROOM': 'Tool Room',
    'MAINTENANCE_BAY': 'Maintenance Bay',
    'SERVER_ROOM': 'Server Room',
    'IT_STORAGE': 'IT Storage / Warehouse',
}


@pytest.fixture
async def seed_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Type Language Org', enabled_modules=['core'])
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def seed_user(
    real_async_db_session: AsyncSession, seed_org: Organization
) -> User:
    user = User(
        email=f'stype_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Type User',
        organization_id=seed_org.id,
        role='admin',
        is_active=True,
        preferred_language='pl',
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


async def _names(db: AsyncSession, organization_id) -> dict[str, str]:
    rows = (
        (
            await db.execute(
                select(StorageType).where(
                    StorageType.organization_id == organization_id
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.type_code: row.name for row in rows}


async def _seed_profiles(db: AsyncSession, organization_id) -> None:
    """Both profile seeders, run the way the application runs them."""
    await db.run_sync(
        lambda session: seed_neutral_storage_types(
            session, organization_id=organization_id, commit=False
        )
    )
    await db.run_sync(
        lambda session: seed_food_storage_types(
            session, organization_id=organization_id, commit=False
        )
    )
    await db.run_sync(
        lambda session: seed_equipment_storage_types(
            session, organization_id=organization_id, commit=False
        )
    )


class TestTheSeedIsWrittenInTheReadersLanguage:
    async def test_a_polish_session_seeds_every_profile_type_in_polish(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
    ) -> None:
        set_current_lang('pl')
        try:
            await _seed_profiles(real_async_db_session, seed_org.id)
            await real_async_db_session.flush()
        finally:
            set_current_lang('en')

        names = await _names(real_async_db_session, seed_org.id)
        assert names['SHELF'] == 'Półka / szafa'
        assert names['FREEZER'] == 'Zamrażarka'
        assert names['MAINTENANCE_BAY'] == 'Stanowisko serwisowe'

    async def test_a_polish_session_seeds_the_declared_types_in_polish(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
    ) -> None:
        set_current_lang('pl')
        try:
            await EquipmentModule()._seed_declared_storage_types(
                seed_org.id, real_async_db_session
            )
            await real_async_db_session.flush()
        finally:
            set_current_lang('en')

        names = await _names(real_async_db_session, seed_org.id)
        assert names['SERVER_ROOM'] == 'Serwerownia'
        assert names['IT_STORAGE'] == 'Magazyn IT'

    async def test_an_english_session_keeps_the_declaration(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
    ) -> None:
        set_current_lang('en')
        await _seed_profiles(real_async_db_session, seed_org.id)
        await real_async_db_session.flush()

        names = await _names(real_async_db_session, seed_org.id)
        assert names['FREEZER'] == 'Freezer'

    async def test_no_seeded_type_is_left_carrying_its_english_literal(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
    ) -> None:
        """The wizard's list, counted: every option but ``SYSTEM`` moved.

        The check walks the names and counts the ones
        still written in ASCII English. ``SYSTEM`` is the one that stays —
        "System" is the Polish word — so the count is over its twelve
        siblings, by code rather than by shape: a name that happens to be
        ASCII ("Magazyn IT") is a translation, and counting letters would
        call it a defect.
        """
        set_current_lang('pl')
        try:
            await _seed_profiles(real_async_db_session, seed_org.id)
            await EquipmentModule()._seed_declared_storage_types(
                seed_org.id, real_async_db_session
            )
            await real_async_db_session.flush()
        finally:
            set_current_lang('en')

        names = await _names(real_async_db_session, seed_org.id)
        assert names['SYSTEM'] == 'System'
        left_in_english = [
            code
            for code, name in names.items()
            if code != 'SYSTEM' and name == ENGLISH_NAMES.get(code)
        ]
        assert left_in_english == []
        assert {code: names[code] for code in POLISH_NAMES} == POLISH_NAMES


class TestARowStillCarryingTheInstallDayEnglish:
    """Organizations seeded before the language was chosen at write time.

    Their rows hold the English literal, which is exactly what says nobody
    has touched them. Seeding again brings those into the language of the
    session doing it; a name that differs is the organization's and is never
    rewritten — by either seeder.
    """

    async def _english_row(
        self, db: AsyncSession, organization_id, name: str
    ) -> StorageType:
        row = StorageType(
            name=name,
            type_code='FREEZER',
            behavior_mode='FREEZING',
            context_schema=[],
            is_system=True,
            organization_id=organization_id,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    async def test_an_untouched_row_joins_the_language(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
    ) -> None:
        await self._english_row(real_async_db_session, seed_org.id, 'Freezer')

        set_current_lang('pl')
        try:
            await _seed_profiles(real_async_db_session, seed_org.id)
            await real_async_db_session.flush()
        finally:
            set_current_lang('en')

        names = await _names(real_async_db_session, seed_org.id)
        assert names['FREEZER'] == 'Zamrażarka'

    async def test_a_renamed_row_keeps_the_name_its_owner_gave_it(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
    ) -> None:
        await self._english_row(real_async_db_session, seed_org.id, 'Zamrażarka Gosi')

        set_current_lang('pl')
        try:
            await _seed_profiles(real_async_db_session, seed_org.id)
            await real_async_db_session.flush()
        finally:
            set_current_lang('en')

        names = await _names(real_async_db_session, seed_org.id)
        assert names['FREEZER'] == 'Zamrażarka Gosi'

    async def test_the_declaration_seeder_leaves_a_renamed_row_alone(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
    ) -> None:
        row = StorageType(
            name='Nasza serwerownia',
            type_code='SERVER_ROOM',
            behavior_mode='NONE',
            context_schema=[],
            is_system=True,
            organization_id=seed_org.id,
        )
        real_async_db_session.add(row)
        await real_async_db_session.commit()

        set_current_lang('pl')
        try:
            await EquipmentModule()._seed_declared_storage_types(
                seed_org.id, real_async_db_session
            )
            await real_async_db_session.flush()
        finally:
            set_current_lang('en')

        names = await _names(real_async_db_session, seed_org.id)
        assert names['SERVER_ROOM'] == 'Nasza serwerownia'
