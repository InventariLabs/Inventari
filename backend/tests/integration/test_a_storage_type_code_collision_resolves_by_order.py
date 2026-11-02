"""Two storage types sharing a code resolve to the same row on every read.

Creation refuses a duplicate type code inside an organization, so the shape is
a legacy one — but it exists, and four readers meet it: the listing, the seed
of the profile's starting locations, a module's declared types and the
profile's own seed. The listing sorts; the other three used to ask Postgres
for the rows with no ORDER BY and let the first or the last one win, so which
row took the seed depended on the table's physical layout — the same
organization could land on one row at one enable and on the other at the next,
with nothing to say anything was ambiguous.

Each test plants the pair in BOTH insertion orders. A reader that sorts picks
the same row either way; one that trusts the heap picks the one inserted
first, or last, and one of the two orders catches it. The row every reader
must agree on is the first by ``(lower(name), name, id)`` — the listing's own
order — here the one called 'Abe'.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.equipment.module import EquipmentModule
from app.seed_profiles.base import seed_neutral_storage_types
from app.services.storage._defaults import create_default_storage_locations_async
from app.services.token_service import get_password_hash

INSERTION_ORDERS = [('Abe', 'Zed'), ('Zed', 'Abe')]


@pytest.fixture
async def collision_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Code Collision Org', enabled_modules=['core'])
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def collision_user(
    real_async_db_session: AsyncSession, collision_org: Organization
) -> User:
    user = User(
        email=f'collision_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Collision User',
        organization_id=collision_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


async def _plant_pair(
    db: AsyncSession, organization_id, code: str, order: tuple[str, str], **fields
) -> dict[str, StorageType]:
    """Insert two rows with *code*, committing between them so the later one
    is physically later, and return them by their name's first word."""
    rows: dict[str, StorageType] = {}
    for label in order:
        row = StorageType(
            name=f'{label} {code}',
            type_code=code,
            organization_id=organization_id,
            **fields,
        )
        db.add(row)
        await db.commit()
        rows[label] = row
    return rows


@pytest.mark.parametrize('order', INSERTION_ORDERS)
class TestACodeCollisionResolvesByTheListingsOrder:
    async def test_the_location_seed_stands_on_the_first_row(
        self,
        real_async_db_session: AsyncSession,
        collision_org: Organization,
        collision_user: User,
        order: tuple[str, str],
    ) -> None:
        db = real_async_db_session
        rows = await _plant_pair(db, collision_org.id, 'SHELF', order)
        await _plant_pair(db, collision_org.id, 'SYSTEM', ('Only',))

        await create_default_storage_locations_async(
            db, collision_org.id, collision_user.id
        )
        await db.flush()

        main = await db.scalar(
            select(StorageLocation).where(
                StorageLocation.organization_id == collision_org.id,
                StorageLocation.name == 'Main Storage',
            )
        )
        assert main is not None
        assert main.storage_type_id == rows['Abe'].id

    async def test_a_module_declaration_refreshes_the_first_row(
        self,
        real_async_db_session: AsyncSession,
        collision_org: Organization,
        order: tuple[str, str],
    ) -> None:
        db = real_async_db_session
        rows = await _plant_pair(
            db, collision_org.id, 'SERVER_ROOM', order, context_schema=['stale']
        )

        await EquipmentModule()._seed_declared_storage_types(collision_org.id, db)
        await db.flush()
        await db.refresh(rows['Abe'])
        await db.refresh(rows['Zed'])

        assert rows['Abe'].context_schema != ['stale']
        assert rows['Zed'].context_schema == ['stale']

    async def test_the_profile_seed_refreshes_the_first_row(
        self,
        real_async_db_session: AsyncSession,
        collision_org: Organization,
        order: tuple[str, str],
    ) -> None:
        db = real_async_db_session
        rows = await _plant_pair(
            db, collision_org.id, 'SHELF', order, behavior_mode='EXPIRY'
        )

        await db.run_sync(
            lambda session: seed_neutral_storage_types(
                session, organization_id=collision_org.id, commit=False
            )
        )
        await db.flush()
        await db.refresh(rows['Abe'])
        await db.refresh(rows['Zed'])

        assert rows['Abe'].behavior_mode == 'STOCK'
        assert rows['Zed'].behavior_mode == 'EXPIRY'
