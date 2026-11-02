"""A fresh Equipment & WMS organization can receive goods.

The equipment module seeds every location it knows with its own context
tag, and the document picker offers only unclaimed locations — the
vertical separation the tag exists for. A fresh install of the package
therefore held two rooms, both claimed, and the receipt dialog answered
"No locations found": the first-use path of the package led nowhere,
and nothing on the screen said why.

The seed gains a neutral receiving location — untagged, so the picker
offers it and the module screens still reach it once goods stand there
(``module_scope`` counts locations holding its records). The guard that
keeps a re-enable from duplicating the tagged rows learns the same trick
for the untagged one: an organization that already holds any unclaimed
location does not need the gift.
"""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.i18n.service import set_current_lang
from app.models.organization import Organization
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.user import User
from app.modules.equipment.module import EquipmentModule
from app.services.module_service import ModuleService
from app.services.onboarding_service import apply_onboarding_profile_async
from app.services.token_service import get_password_hash


@pytest.fixture
async def seed_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Fresh Package Org', enabled_modules=['core'])
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def seed_user(
    real_async_db_session: AsyncSession, seed_org: Organization
) -> User:
    user = User(
        email=f'fresh_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Fresh Package User',
        organization_id=seed_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


async def _seed(db: AsyncSession, org: Organization, user: User) -> None:
    await EquipmentModule()._seed_default_storage_locations(org.id, db, user)
    await db.flush()


async def _rows(db: AsyncSession, organization_id) -> list[StorageLocation]:
    return (
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


class TestTheSeedLeavesANeutralDoor:
    async def test_seeding_writes_an_untagged_receiving_location(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        await _seed(real_async_db_session, seed_org, seed_user)

        rows = await _rows(real_async_db_session, seed_org.id)
        neutral = [row for row in rows if row.context_tag is None]
        assert len(neutral) == 1
        assert neutral[0].behavior_mode == 'STOCK'
        assert neutral[0].settings['seed']['code'] == 'MAIN_WAREHOUSE'

    async def test_a_polish_session_writes_the_polish_name(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        set_current_lang('pl')
        try:
            await _seed(real_async_db_session, seed_org, seed_user)
        finally:
            set_current_lang('en')

        rows = await _rows(real_async_db_session, seed_org.id)
        neutral = [row for row in rows if row.context_tag is None]
        assert neutral[0].name == 'Magazyn główny'

    async def test_reenabling_does_not_duplicate_the_neutral_location(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        await _seed(real_async_db_session, seed_org, seed_user)
        await _seed(real_async_db_session, seed_org, seed_user)

        count = (
            await real_async_db_session.execute(
                select(func.count())
                .select_from(StorageLocation)
                .where(
                    StorageLocation.organization_id == seed_org.id,
                    StorageLocation.context_tag.is_(None),
                )
            )
        ).scalar_one()
        assert count == 1

    async def test_an_organization_with_its_own_untagged_location_is_left_alone(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        real_async_db_session.add(
            StorageLocation(
                name='Shelf They Made',
                behavior_mode='STOCK',
                usage='internal',
                organization_id=seed_org.id,
                created_by=seed_user.id,
            )
        )
        await real_async_db_session.flush()

        await _seed(real_async_db_session, seed_org, seed_user)

        rows = await _rows(real_async_db_session, seed_org.id)
        neutral = [row for row in rows if row.context_tag is None]
        assert [row.name for row in neutral] == ['Shelf They Made']


async def _virtual_counterparts(
    db: AsyncSession, org: Organization, user: User
) -> None:
    """The three virtual rows an organization carries besides its shelves.

    They are untagged like the neutral location, which is exactly why the
    guard mistook them for one: the picker never offers them — they are
    move targets, not places goods may land.
    """
    for name, usage in (
        ('Consumed', LocationUsage.CUSTOMER),
        ('Inventory Loss', LocationUsage.INVENTORY),
        ('Production', LocationUsage.PRODUCTION),
    ):
        db.add(
            StorageLocation(
                name=name,
                behavior_mode='STOCK',
                usage=usage,
                organization_id=org.id,
                created_by=user.id,
            )
        )
    await db.flush()


def _user_ctx(user: User) -> UserContextDTO:
    return UserContextDTO(
        id=user.id,
        organization_id=user.organization_id,
        role=user.role,
        email=user.email,
    )


def _offerable(rows: list[StorageLocation]) -> list[str]:
    """The rows the document picker would offer: internal and unarchived."""
    return [
        row.name
        for row in rows
        if row.context_tag is None
        and row.usage == LocationUsage.INTERNAL
        and (row.settings or {}).get('archived') is not True
    ]


class TestTheGuardAsksWhatThePickerOffers:
    """The neutral seed is skipped only when the picker has something to show.

    An organization whose only unclaimed locations are the virtual
    counterparts or an archived shelf has nothing the document picker can
    offer, so the guard that reads "they already have a place to land goods"
    was false — and a re-enable through Settings left the receipt dialog
    with nothing in it.
    """

    async def test_virtual_counterparts_are_not_a_reason_to_skip_the_seed(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        await _virtual_counterparts(real_async_db_session, seed_org, seed_user)

        await _seed(real_async_db_session, seed_org, seed_user)

        rows = await _rows(real_async_db_session, seed_org.id)
        assert _offerable(rows) == ['Main Warehouse']

    async def test_an_archived_location_is_not_a_place_to_land_goods(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        real_async_db_session.add(
            StorageLocation(
                name='Old Shelf',
                behavior_mode='STOCK',
                usage='internal',
                settings={'archived': True},
                organization_id=seed_org.id,
                created_by=seed_user.id,
            )
        )
        await real_async_db_session.flush()

        await _seed(real_async_db_session, seed_org, seed_user)

        rows = await _rows(real_async_db_session, seed_org.id)
        assert _offerable(rows) == ['Main Warehouse']

    async def test_the_settings_toggle_seeds_the_neutral_location(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        """The path the defect was measured on: enabling from Settings."""
        await _virtual_counterparts(real_async_db_session, seed_org, seed_user)

        await ModuleService.toggle_module(
            real_async_db_session,
            seed_org,
            'equipment',
            True,
            _user_ctx(seed_user),
        )

        rows = await _rows(real_async_db_session, seed_org.id)
        assert _offerable(rows) == ['Main Warehouse']

    async def test_the_onboarding_profile_seeds_the_neutral_location(
        self,
        real_async_db_session: AsyncSession,
        seed_org: Organization,
        seed_user: User,
    ) -> None:
        """The other enable path: a profile applied to a fresh organization.

        The equipment profile seeds a quarantine shelf of its own beside the
        neutral door — that shelf is what a receipt carrying a damaged unit
        is booked onto, and it is offered like any other place goods land.
        """
        await _virtual_counterparts(real_async_db_session, seed_org, seed_user)

        await apply_onboarding_profile_async(
            real_async_db_session,
            seed_org,
            'equipment_wms',
            user=_user_ctx(seed_user),
        )

        rows = await _rows(real_async_db_session, seed_org.id)
        assert sorted(_offerable(rows)) == ['Main Warehouse', 'Quarantine']
