"""A location a module seeds is named in the language it was enabled in.

The seeded name used to be an English literal from install day -- "Server
Room" sitting in a Polish interface -- and one module carried a translation
handle to paper over it at display time. That covered React screens and
nothing else: the path under the picker, the search box, the printed label on
the door and every exported document still read the stored name, so the same
room answered to two names depending on where you looked.

A location's name is data. It is editable, it is printed, it is exported: the
place to choose its language is the moment it is written, once, and every
reader agrees from then on.
"""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n.service import set_current_lang
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.equipment.module import EquipmentModule
from app.services.token_service import get_password_hash


@pytest.fixture
async def seed_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Seed Language Org', enabled_modules=['core'])
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def seed_user(
    real_async_db_session: AsyncSession, seed_org: Organization
) -> User:
    user = User(
        email=f'seed_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Seed User',
        organization_id=seed_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


async def _names(db: AsyncSession, organization_id) -> dict[str, StorageLocation]:
    rows = (
        (
            await db.execute(
                select(StorageLocation).where(
                    StorageLocation.organization_id == organization_id
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        (row.settings or {}).get('seed', {}).get('code', row.name): row for row in rows
    }


async def _row_count(db: AsyncSession, organization_id) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(StorageLocation)
            .where(StorageLocation.organization_id == organization_id)
        )
    ).scalar_one()


class TestTheSeedIsWrittenInTheReadersLanguage:
    async def test_polish_session_seeds_polish_names(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        set_current_lang('pl')
        try:
            await EquipmentModule()._seed_default_storage_locations(
                seed_org.id, real_async_db_session, seed_user
            )
            await real_async_db_session.flush()
        finally:
            set_current_lang('en')

        rows = await _names(real_async_db_session, seed_org.id)
        assert rows['SERVER_ROOM'].name == 'Serwerownia'
        assert rows['IT_STORAGE'].name == 'Magazyn IT'
        # The handle records what was written, not the English it came from --
        # otherwise every later pass reads the row as still untouched.
        assert rows['SERVER_ROOM'].settings['seed']['name'] == 'Serwerownia'

    async def test_a_language_without_a_translation_keeps_the_declaration(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        set_current_lang('en')
        await EquipmentModule()._seed_default_storage_locations(
            seed_org.id, real_async_db_session, seed_user
        )
        await real_async_db_session.flush()

        rows = await _names(real_async_db_session, seed_org.id)
        assert rows['SERVER_ROOM'].name == 'Server Room'


class TestARowStillCarryingTheInstallDayEnglish:
    """Organizations seeded before the language was chosen at write time.

    Their rows hold the English literal and a handle recording that same
    literal, which is exactly what says nobody has touched them. Enabling the
    module again brings those into the language of the session doing it, once:
    the handle then records the new name, so a later enable in a third
    language leaves the row alone. A row the user renamed is never touched,
    whichever language anyone enables in.
    """

    async def _seed_english_row(
        self, db: AsyncSession, organization_id, user, name: str
    ) -> StorageLocation:
        row = StorageLocation(
            name=name,
            behavior_mode='NONE',
            context_tag='equipment',
            usage='internal',
            organization_id=organization_id,
            created_by=user.id,
            settings={'seed': {'code': 'SERVER_ROOM', 'name': 'Server Room'}},
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    async def test_an_untouched_row_joins_the_language(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        await self._seed_english_row(
            real_async_db_session, seed_org.id, seed_user, 'Server Room'
        )

        set_current_lang('pl')
        try:
            await EquipmentModule()._seed_default_storage_locations(
                seed_org.id, real_async_db_session, seed_user
            )
            await real_async_db_session.flush()
        finally:
            set_current_lang('en')

        rows = await _names(real_async_db_session, seed_org.id)
        assert rows['SERVER_ROOM'].name == 'Serwerownia'
        assert rows['SERVER_ROOM'].settings['seed']['name'] == 'Serwerownia'
        # The guard against duplicating the tagged seed still holds: exactly
        # one equipment-tagged row exists, and the only other row is the
        # untagged door the document picker needs (see
        # test_a_fresh_package_takes_delivery.py).
        assert sum(1 for row in rows.values() if row.context_tag == 'equipment') == 1
        assert sum(1 for row in rows.values() if row.context_tag is None) == 1
        # The two sums above are per tag, so a third row under yet another tag
        # would pass both; the total is what closes that. It counts rows, not
        # the dict above, which folds rows sharing a handle into one.
        assert await _row_count(real_async_db_session, seed_org.id) == 2

    async def test_a_renamed_row_keeps_the_name_its_owner_gave_it(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        await self._seed_english_row(
            real_async_db_session, seed_org.id, seed_user, 'Basement rack'
        )

        set_current_lang('pl')
        try:
            await EquipmentModule()._seed_default_storage_locations(
                seed_org.id, real_async_db_session, seed_user
            )
            await real_async_db_session.flush()
        finally:
            set_current_lang('en')

        rows = await _names(real_async_db_session, seed_org.id)
        assert rows['SERVER_ROOM'].name == 'Basement rack'
