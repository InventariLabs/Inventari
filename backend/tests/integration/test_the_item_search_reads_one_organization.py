"""The item search reads the records of the asking organization only.

Two organizations hold a record whose text matches. The search predicate is
run on its own, without the outer organization scope the list adds, so what
it returns is what the database read for the search: the asking
organization's records through the own-fields branch and through the
product-code branch, and nothing of the other organization's.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.services.items._search_terms import item_matches_text
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration

_TEXT = 'kawa'


async def _record(db: AsyncSession, org_id, user_id, name: str, **own) -> Item:
    shelf = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        name=f'Shelf {name}',
        usage=LocationUsage.INTERNAL,
    )
    template = ProductTemplate(organization_id=org_id, name=name, **own)
    db.add_all([shelf, template])
    await db.flush()
    item = Item(
        organization_id=org_id,
        storage_location_id=shelf.id,
        name=name,
        quantity=Decimal('1'),
        template_id=template.id,
    )
    db.add(item)
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return item


@pytest.mark.asyncio
class TestTheSearchStaysInsideTheOrganization:
    async def test_matches_of_another_organization_are_not_read(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        mine_org = async_test_user.organization_id
        other = Organization(name='Elsewhere', enabled_modules=['core'])
        db.add(other)
        await db.flush()

        by_name_mine = await _record(db, mine_org, async_test_user.id, 'Kawa moja')
        by_name_theirs = await _record(db, other.id, async_test_user.id, 'Kawa ich')
        by_code_mine = await _record(
            db, mine_org, async_test_user.id, 'Herbata moja', barcode='KAWA-MINE'
        )
        by_code_theirs = await _record(
            db, other.id, async_test_user.id, 'Herbata ich', barcode='KAWA-THEIRS'
        )

        found = set(
            (
                await db.execute(
                    select(Item.id).where(item_matches_text(_TEXT, mine_org))
                )
            ).scalars()
        )

        assert found == {by_name_mine.id, by_code_mine.id}
        assert not found & {by_name_theirs.id, by_code_theirs.id}

    async def test_without_an_organization_both_are_read(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        """The control: the same data, no scope, and the other side shows up."""
        db = real_async_db_session
        other = Organization(name=f'Elsewhere {uuid.uuid4()}', enabled_modules=['core'])
        db.add(other)
        await db.flush()
        theirs = await _record(db, other.id, async_test_user.id, 'Kawa ich')

        found = set(
            (
                await db.execute(select(Item.id).where(item_matches_text(_TEXT, None)))
            ).scalars()
        )

        assert theirs.id in found
