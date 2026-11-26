"""Emptying a record leaves the organization's virtual places named as they are.

The places are one set for the whole organization, and whoever uses up the
last of something reads and writes them in their own language. Their names
follow onboarding, not the person acting; a place that is missing is made, in
the language of the request that needed it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n.service import set_current_lang
from app.models.storage_location import LocationUsage
from app.schemas.item import ItemConsumeRequest
from app.services.items import consume_item
from app.services.storage._defaults import (
    ensure_virtual_locations_async,
    get_virtual_location_async,
)

from ._core_api_helpers import make_template
from ._shelf import put_on_shelf, shelf_keeper

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.parametrize(
    ('missing', 'consumed_name'),
    [
        pytest.param(False, 'Consumed (Virtual)', id='every-place-there'),
        pytest.param(True, 'Zużyte (wirtualna)', id='consumed-place-missing'),
    ],
)
async def test_using_up_the_last_unit_renames_no_virtual_place(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    missing: bool,
    consumed_name: str,
) -> None:
    db = real_async_db_session
    org_id = str(async_test_household.id)
    template = await db.run_sync(
        lambda s: make_template(s, async_test_household.id, name='Rice')
    )
    keeper = await shelf_keeper(db, async_test_household.id)
    await ensure_virtual_locations_async(db, org_id, str(keeper.id))
    if missing:
        consumed = await get_virtual_location_async(db, org_id, LocationUsage.CUSTOMER)
        await db.delete(consumed)
        await db.flush()
    record = await put_on_shelf(db, keeper, template, async_test_storage_location.id, 1)

    set_current_lang('pl')
    try:
        await consume_item(
            db, record, ItemConsumeRequest(quantity=Decimal('1')), keeper
        )
    finally:
        set_current_lang('en')

    names = {}
    for usage in (LocationUsage.CUSTOMER, LocationUsage.INVENTORY):
        place = await get_virtual_location_async(db, org_id, usage)
        assert place is not None
        names[usage] = place.name
    assert names == {
        LocationUsage.CUSTOMER: consumed_name,
        LocationUsage.INVENTORY: 'Inventory Loss (Virtual)',
    }
    assert (
        record.storage_location_id
        == (await get_virtual_location_async(db, org_id, LocationUsage.CUSTOMER)).id
    )
