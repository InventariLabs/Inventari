"""The module seeder and the profile seeder agree on which names are untouched.

Both write a storage type's name in the reader's language and both move a row
that still bears the declaration's own literal; neither rewrites a name the
organization changed. The profile seeder asks only whether the name is still
the literal, so the module seeder must too: a type the organization forked from
a global one (and so is not flagged as seeded) is as unrenamed as any other.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.i18n.service import set_current_lang
from app.models.organization import Organization
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.equipment.module import EquipmentModule


async def _enable_equipment_in_polish(
    session: AsyncSession, *, existing_name: str, is_system: bool
) -> StorageType:
    """Give an organization a SERVER_ROOM type, then enable the module."""
    org = Organization(
        name=f'Seed Org {uuid.uuid4().hex[:8]}', enabled_modules=['core']
    )
    session.add(org)
    await session.flush()
    user = User(
        email=f'user_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password='x',
        full_name='Seeder',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(
        StorageType(
            name=existing_name,
            type_code='SERVER_ROOM',
            behavior_mode='NONE',
            is_system=is_system,
            organization_id=org.id,
        )
    )
    await session.flush()

    set_current_lang('pl')
    try:
        await EquipmentModule().system_on_enable(
            org.id,
            session,
            user=UserContextDTO(id=user.id, organization_id=org.id, role='admin'),
        )
    finally:
        set_current_lang('en')
    await session.flush()
    return (
        await session.scalars(
            select(StorageType).where(
                StorageType.organization_id == org.id,
                StorageType.type_code == 'SERVER_ROOM',
            )
        )
    ).one()


@pytest.mark.integration
class TestDeclaredStorageTypeNamesFollowTheReader:
    async def test_a_forked_row_still_bearing_the_literal_joins_the_language(
        self, real_async_db_session: AsyncSession
    ) -> None:
        row = await _enable_equipment_in_polish(
            real_async_db_session, existing_name='Server Room', is_system=False
        )
        assert row.name == 'Serwerownia'

    async def test_a_seeded_row_still_bearing_the_literal_joins_the_language(
        self, real_async_db_session: AsyncSession
    ) -> None:
        row = await _enable_equipment_in_polish(
            real_async_db_session, existing_name='Server Room', is_system=True
        )
        assert row.name == 'Serwerownia'

    async def test_a_renamed_row_is_left_alone(
        self, real_async_db_session: AsyncSession
    ) -> None:
        row = await _enable_equipment_in_polish(
            real_async_db_session, existing_name='Our racks', is_system=False
        )
        assert row.name == 'Our racks'
