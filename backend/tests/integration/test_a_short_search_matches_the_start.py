"""One or two letters typed into the product list match how a field begins.

"he" anywhere in a name is inside a large share of any catalogue, and a
fragment that short has no trigram the indexes can look up except at the
start of a value: the list search read every record of the organization
(557/690 ms p50/p95 at a hundred thousand products) to show fifty. The
product picker already matched one or two letters at the start of the name;
the list now does the same, and from three letters on matches anywhere.

The product code behind a record is matched whole by a fragment that short,
as the picker matches it: a code's first one or two digits are its
country's (every Polish EAN begins 590), so their start named a whole
catalogue and the list carried every product id into the statement —
twenty-four seconds for "2" at a hundred thousand products.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.services.items._search_terms import item_matches_text
from tests.integration._shelf import anchor_pending_records

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def records(real_async_db_session: AsyncSession, async_test_user):
    db = real_async_db_session
    org_id = async_test_user.organization_id
    shelf = StorageLocation(
        organization_id=org_id,
        created_by=async_test_user.id,
        name='Shelf',
        usage=LocationUsage.INTERNAL,
    )
    coded = ProductTemplate(organization_id=org_id, name='Nails', barcode='4200')
    short_code = ProductTemplate(organization_id=org_id, name='Glue', barcode='42')
    db.add_all([shelf, coded, short_code])
    await db.flush()
    rows = {}
    for name, extra in (
        ('Hex bolt', {}),
        ('Wheel', {}),
        ('Nails', {'template_id': coded.id}),
        ('Glue', {'template_id': short_code.id}),
        ('Washer', {'brand': 'Heller'}),
    ):
        rows[name] = Item(
            organization_id=org_id,
            storage_location_id=shelf.id,
            name=name,
            quantity=Decimal('1'),
            **extra,
        )
    db.add_all(rows.values())
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return {'org_id': org_id, **{name: row.id for name, row in rows.items()}}


async def _found(db: AsyncSession, text: str, org_id) -> set:
    return set(
        (await db.execute(select(Item.id).where(item_matches_text(text, org_id))))
        .scalars()
        .all()
    )


async def test_two_letters_match_the_start_of_each_field(
    real_async_db_session: AsyncSession, records
):
    found = await _found(real_async_db_session, 'he', records['org_id'])

    assert records['Hex bolt'] in found
    assert records['Washer'] in found  # the brand begins with it
    assert records['Wheel'] not in found


async def test_two_characters_match_a_product_code_whole(
    real_async_db_session: AsyncSession, records
):
    found = await _found(real_async_db_session, '42', records['org_id'])

    assert records['Glue'] in found  # the product code is it
    assert records['Nails'] not in found  # its code only begins with it


async def test_three_letters_match_anywhere(
    real_async_db_session: AsyncSession, records
):
    found = await _found(real_async_db_session, 'hee', records['org_id'])

    assert found == {records['Wheel']}


async def test_three_letters_match_anywhere_in_a_product_code(
    real_async_db_session: AsyncSession, records
):
    found = await _found(real_async_db_session, '200', records['org_id'])

    assert found == {records['Nails']}


async def test_a_short_fragment_is_still_a_literal(
    real_async_db_session: AsyncSession, records
):
    assert await _found(real_async_db_session, '%e', records['org_id']) == set()
