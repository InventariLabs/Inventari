"""The code a scan writes is the code the lists read back.

A scanned barcode belongs to the product template — the record stays bare,
so the second delivery of the same product does not die on the uniqueness
index. The reading side never learned that: ``?search=<code>`` matched
``Item.barcode`` alone, so a product the organization had just scanned in
answered "no results" when its own code was typed back, and the user had no
way to confirm the scan had landed.

The search now asks both carriers — the record's own code (a one-off with
no catalogue entry keeps it there) and its template's.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.services.items._list import search_by_org_async
from app.services.items._query_get import get_items
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


def _barcode() -> str:
    return f'76{uuid.uuid4().int % 10**11:011d}'


async def _location_async(db: AsyncSession, org_id, user_id) -> StorageLocation:
    location = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        name='Main Warehouse',
        usage=LocationUsage.INTERNAL,
    )
    db.add(location)
    await db.flush()
    return location


@pytest.mark.asyncio
class TestTheCodeIsFoundOnEitherCarrier:
    async def test_a_code_on_the_template_finds_the_record(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        barcode = _barcode()
        template = ProductTemplate(
            organization_id=org_id, name='Kawa mielona', barcode=barcode
        )
        db.add(template)
        await db.flush()
        location = await _location_async(db, org_id, async_test_user.id)
        db.add(
            Item(
                organization_id=org_id,
                storage_location_id=location.id,
                name='Kawa mielona',
                quantity=Decimal('3'),
                template_id=template.id,
            )
        )
        await db.run_sync(anchor_pending_records)
        await db.commit()

        items, total = await search_by_org_async(db, org_id, query_text=barcode)

        assert total == 1, 'the product carries this code — through its template'
        assert items[0].name == 'Kawa mielona'

    async def test_the_records_own_code_still_finds_it(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        """The one-off without a catalogue entry keeps the code on the row."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        barcode = _barcode()
        location = await _location_async(db, org_id, async_test_user.id)
        db.add(
            Item(
                organization_id=org_id,
                storage_location_id=location.id,
                name='Jednorazówka',
                quantity=Decimal('1'),
                barcode=barcode,
            )
        )
        await db.commit()

        items, total = await search_by_org_async(db, org_id, query_text=barcode)

        assert total == 1
        assert items[0].name == 'Jednorazówka'


class TestTheFilteredListAnswersTheSame:
    """Two entry points, one answer: the items list and the search box must
    not disagree about what a product code finds."""

    def test_the_items_list_finds_a_code_on_the_template(
        self, db_session: Session, test_user
    ) -> None:
        org_id = test_user.organization_id
        barcode = _barcode()
        template = ProductTemplate(
            organization_id=org_id, name='Herbata', barcode=barcode
        )
        db_session.add(template)
        db_session.flush()
        location = StorageLocation(
            organization_id=org_id,
            created_by=test_user.id,
            name='Main Warehouse',
            usage=LocationUsage.INTERNAL,
        )
        db_session.add(location)
        db_session.flush()
        db_session.add(
            Item(
                organization_id=org_id,
                storage_location_id=location.id,
                name='Herbata',
                quantity=Decimal('2'),
                template_id=template.id,
            )
        )
        anchor_pending_records(db_session)
        db_session.commit()

        items, total = get_items(db_session, organization_id=org_id, search=barcode)

        assert total == 1
        assert items[0].name == 'Herbata'
