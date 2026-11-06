"""The start-location declaration is a core mechanism, not an equipment one.

``StorageLocationDeclaration`` and the seeder behind it live in the core, yet
the only module that used them was equipment, so every property the mechanism
promises was witnessed by one declaration list. A module with a tag of its
own, a translation of its own and no connection to equipment is the second
witness: if the guard or the language choice quietly depended on equipment's
names, this module is where it would show.
"""

from uuid import uuid4

import pytest
from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.modules import (
    BaseModule,
    LocalizedText,
    ModuleMetadata,
    StorageLocationDeclaration,
)
from app.i18n.service import set_current_lang
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.services.token_service import get_password_hash


class _BakeryModule(BaseModule):
    """A module that has nothing to do with equipment and declares two places."""

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name='bakery_probe',
            version='1.0.0',
            display_name='Bakery probe',
            description='',
            icon='box',
            default_storage_locations=[
                StorageLocationDeclaration(
                    name='Proving Room',
                    code='PROVING_ROOM',
                    context_tag='bakery_probe',
                    translations={'pl': LocalizedText(name='Garowanie')},
                ),
                StorageLocationDeclaration(name='Bakery Dock', code='BAKERY_DOCK'),
            ],
        )

    def register_routes(self) -> APIRouter:
        return APIRouter()


@pytest.fixture
async def seed_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Second Consumer Org', enabled_modules=['core'])
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def seed_user(
    real_async_db_session: AsyncSession, seed_org: Organization
) -> User:
    user = User(
        email=f'bakery_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Bakery User',
        organization_id=seed_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


async def _rows(db: AsyncSession, organization_id) -> list[StorageLocation]:
    return list(
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


async def _enable(db: AsyncSession, org: Organization, user: User, lang: str) -> None:
    set_current_lang(lang)
    try:
        await _BakeryModule()._seed_default_storage_locations(org.id, db, user)
        await db.flush()
    finally:
        set_current_lang('en')


class TestAModuleWithNoTiesToEquipment:
    async def test_it_seeds_its_tagged_and_its_untagged_place(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        await _enable(real_async_db_session, seed_org, seed_user, 'en')

        rows = {
            row.settings['seed']['code']: row
            for row in await _rows(real_async_db_session, seed_org.id)
        }
        assert set(rows) == {'PROVING_ROOM', 'BAKERY_DOCK'}
        assert rows['PROVING_ROOM'].context_tag == 'bakery_probe'
        assert rows['BAKERY_DOCK'].context_tag is None

    async def test_it_writes_the_name_in_the_language_it_is_enabled_in(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        await _enable(real_async_db_session, seed_org, seed_user, 'pl')

        rows = {
            row.settings['seed']['code']: row
            for row in await _rows(real_async_db_session, seed_org.id)
        }
        assert rows['PROVING_ROOM'].name == 'Garowanie'
        # No Polish entry declared: the declaration's own name stands.
        assert rows['BAKERY_DOCK'].name == 'Bakery Dock'

    async def test_enabling_again_stacks_no_second_copy(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        await _enable(real_async_db_session, seed_org, seed_user, 'en')
        await _enable(real_async_db_session, seed_org, seed_user, 'en')

        rows = await _rows(real_async_db_session, seed_org.id)
        assert len(rows) == 2

    async def test_an_untouched_row_joins_the_language_of_a_later_enable(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        await _enable(real_async_db_session, seed_org, seed_user, 'en')
        await _enable(real_async_db_session, seed_org, seed_user, 'pl')

        rows = {
            row.settings['seed']['code']: row
            for row in await _rows(real_async_db_session, seed_org.id)
        }
        assert rows['PROVING_ROOM'].name == 'Garowanie'
        assert len(rows) == 2

    async def test_a_renamed_row_keeps_the_name_its_owner_gave_it(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        await _enable(real_async_db_session, seed_org, seed_user, 'en')
        proving = next(
            row
            for row in await _rows(real_async_db_session, seed_org.id)
            if row.context_tag == 'bakery_probe'
        )
        proving.name = 'Our proving cabinet'
        await real_async_db_session.flush()

        await _enable(real_async_db_session, seed_org, seed_user, 'pl')

        await real_async_db_session.refresh(proving)
        assert proving.name == 'Our proving cabinet'
