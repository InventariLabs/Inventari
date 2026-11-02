"""`qa fixture --variant one` — one core record, where the core list shows it.

The variant exists to put a list with exactly one row on screen. On an
organization provisioned with a module profile it took the first category it
found, a module's, and the product disappeared from the core list: the "one"
column of the coverage register read uncovered over a screen that had been
visited.

Its template took the first unit row of the whole catalogue — any symbol, any
organization — or none at all, the shape every other door refuses.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.module_ownership import unclaimed_by_a_module
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _module_profile_org(db: AsyncSession) -> tuple[Organization, User]:
    """An organization whose only category and shelf belong to a module."""
    from app.services.auth_service import get_password_hash

    org = Organization(name=f'QA One {uuid.uuid4().hex[:6]}')
    db.add(org)
    await db.flush()
    user = User(
        email=f'{uuid.uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('testpassword123'),
        full_name='QA One',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add_all(
        [
            Category(
                organization_id=org.id,
                name='Laptops',
                icon='laptop',
                context_tag='equipment',
            ),
            StorageLocation(
                organization_id=org.id,
                name='IT Store',
                context_tag='equipment',
                created_by=user.id,
            ),
        ]
    )
    await db.flush()
    return org, user


async def test_the_one_record_is_filed_where_the_core_list_shows_it(
    real_async_db_session: AsyncSession,
):
    from app.cli.commands_qa import _seed_one

    db = real_async_db_session
    org, user = await _module_profile_org(db)

    await _seed_one(db, org, user)

    item = (await db.scalars(select(Item).where(Item.organization_id == org.id))).one()
    category = await db.get(Category, item.category_id)
    location = await db.get(StorageLocation, item.storage_location_id)
    assert category.context_tag is None
    assert location.context_tag is None
    # The core list's own rule, with the equipment module claiming its tag.
    shown = await db.scalar(
        select(func.count())
        .select_from(Item)
        .where(Item.organization_id == org.id, unclaimed_by_a_module({'equipment'}))
    )
    assert shown == 1


async def test_the_template_takes_the_organizations_piece(
    real_async_db_session: AsyncSession,
):
    from app.cli.commands_qa import _seed_one

    db = real_async_db_session
    org, user = await _module_profile_org(db)

    await _seed_one(db, org, user)

    # One of each: the one template is the one the one record stands on.
    template = (
        await db.scalars(
            select(ProductTemplate).where(ProductTemplate.organization_id == org.id)
        )
    ).one()
    item = (await db.scalars(select(Item).where(Item.organization_id == org.id))).one()
    assert item.template_id == template.id
    uom = await db.get(Uom, template.uom_id)
    assert uom.symbol == 'pcs'
    assert uom.organization_id in (None, org.id)


async def test_a_catalogue_without_pieces_is_refused_not_answered_with_a_blank(
    real_async_db_session: AsyncSession, monkeypatch
):
    from app.cli.commands_qa import _seed_one
    from app.services import uom_service

    async def no_unit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(uom_service, 'get_uom_by_symbol_async', no_unit)
    db = real_async_db_session
    org, user = await _module_profile_org(db)

    with pytest.raises(ServiceRejectionError):
        await _seed_one(db, org, user)

    assert (
        await db.scalar(
            select(func.count())
            .select_from(ProductTemplate)
            .where(ProductTemplate.organization_id == org.id)
        )
    ) == 0
