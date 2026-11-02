"""A scanned barcode belongs to the product template, so that is where it is read.

Scanning a package answered "New product found" and opened an empty New
Product form -- an invitation to create a duplicate -- for a product the
organization held twelve of. The provider matched ``Item.barcode``, and in a
real database that column is empty: 243 templates carried a barcode, 0 of 1814
items did. The template owns the code (see ``_stock_executor_receipt``), and
``uq_items_org_barcode_active`` lets only one active row bear one anyway --
which is why the summary branch, written to sum many rows and list many
locations, could never have more than one of either.

The same question is answered correctly next door: ``find_stock_row_async``
resolves identity by template when a line names one, and by barcode only for
records that have no template. This holds the scan to that precedence.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scan_providers import BarcodeScanProvider
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.uom import Uom
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


def _barcode() -> str:
    return f'76{uuid.uuid4().int % 10**11:011d}'


async def _location(db: AsyncSession, org_id, user_id, name: str) -> StorageLocation:
    location = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        name=name,
        usage=LocationUsage.INTERNAL,
    )
    db.add(location)
    await db.flush()
    return location


async def _template(db: AsyncSession, org_id, barcode: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org_id,
        name='Kawa mielona Jacobs',
        brand='Jacobs',
        barcode=barcode,
        sku='JAC-250',
        weight_value=Decimal('0.25'),
    )
    db.add(template)
    await db.flush()
    return template


async def _item(db: AsyncSession, org_id, location, quantity: str, **kwargs) -> Item:
    item = Item(
        organization_id=org_id,
        storage_location_id=location.id,
        name=kwargs.pop('name', 'Kawa mielona Jacobs'),
        quantity=Decimal(quantity),
        **kwargs,
    )
    db.add(item)
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return item


@pytest.mark.asyncio
class TestTheScanFindsStockThroughTheTemplate:
    async def test_stock_standing_in_two_places_is_summed_and_both_are_named(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        barcode = _barcode()
        template = await _template(db, org_id, barcode)
        shelf = await _location(db, org_id, async_test_user.id, 'Main Warehouse')
        cellar = await _location(db, org_id, async_test_user.id, 'Cellar')
        await _item(db, org_id, shelf, '8', template_id=template.id)
        await _item(db, org_id, cellar, '4', template_id=template.id)
        await db.commit()

        result = await BarcodeScanProvider().handle(barcode, async_test_user, db)

        assert result is not None
        assert result.status == 'product_stock'
        assert result.action == 'show_stock_actions'
        summary = result.stock_summary
        assert summary is not None
        assert summary['total_quantity'] == 12.0
        # The branch sums rows and lists places; with the match on the item's
        # own barcode it could only ever have had one of each.
        assert sorted(summary['locations']) == ['Cellar', 'Main Warehouse']
        assert len(summary['items']) == 2

    async def test_each_record_names_its_shelf_and_the_product_its_removal_order(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        # A document taking goods off one shelf cannot pick a record from a
        # location *name*; it needs the shelf's id, the order the product
        # leaves in, and the age FIFO is judged by.
        db = real_async_db_session
        org_id = async_test_user.organization_id
        barcode = _barcode()
        template = await _template(db, org_id, barcode)
        template.removal_strategy = 'FEFO'
        shelf = await _location(db, org_id, async_test_user.id, 'Main Warehouse')
        item = await _item(db, org_id, shelf, '8', template_id=template.id)
        await db.commit()

        result = await BarcodeScanProvider().handle(barcode, async_test_user, db)

        assert result is not None
        summary = result.stock_summary
        assert summary is not None
        assert summary['removal_strategy'] == 'FEFO'
        [row] = summary['items']
        assert row['id'] == str(item.id)
        assert row['location_id'] == str(shelf.id)
        assert row['created_at'] == item.created_at.isoformat()

    async def test_a_product_with_no_strategy_of_its_own_leaves_first_in_first_out(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        barcode = _barcode()
        template = await _template(db, org_id, barcode)
        shelf = await _location(db, org_id, async_test_user.id, 'Main Warehouse')
        await _item(db, org_id, shelf, '8', template_id=template.id)
        await db.commit()

        result = await BarcodeScanProvider().handle(barcode, async_test_user, db)

        assert result is not None and result.stock_summary is not None
        assert result.stock_summary['removal_strategy'] == 'FIFO'

    async def test_a_template_the_organization_holds_none_of_prefills_the_form(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        # Still "add one", but not from a blank form: the catalogue already
        # knows the name, the brand and the unit weight of what was scanned.
        db = real_async_db_session
        barcode = _barcode()
        template = await _template(db, async_test_user.organization_id, barcode)
        await db.commit()

        result = await BarcodeScanProvider().handle(barcode, async_test_user, db)

        assert result is not None
        assert result.action == 'show_quick_add'
        assert result.stock_summary is not None
        assert result.stock_summary['template']['name'] == template.name
        assert result.stock_summary['template']['sku'] == 'JAC-250'
        # A document line that points at the product but no stock record
        # recognises the scan by this id.
        assert result.stock_summary['template']['id'] == str(template.id)

    async def test_the_unit_comes_back_with_the_template(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        # The payload reads the template's unit, and a relationship touched
        # outside a load raises rather than answering in an async session --
        # so a template that HAS a unit is the case that proves it is loaded.
        db = real_async_db_session
        uom = (await db.scalars(select(Uom).limit(1))).first()
        assert uom is not None, 'the base seed provides units'
        barcode = _barcode()
        template = await _template(db, async_test_user.organization_id, barcode)
        template.uom_id = uom.id
        await db.commit()
        # Otherwise the relationship is answered from the session's identity
        # map, without IO, and the test passes whether or not the query loads
        # it -- which is not the case in a request that only scans.
        db.expunge_all()

        result = await BarcodeScanProvider().handle(barcode, async_test_user, db)

        assert result is not None
        assert result.stock_summary is not None
        assert result.stock_summary['template']['unit'] == uom.symbol

    async def test_a_record_with_no_template_is_still_found_by_its_own_barcode(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        # Such a record owns the code -- there is no template to ask -- and
        # that is the one case the item column still answers.
        db = real_async_db_session
        org_id = async_test_user.organization_id
        barcode = _barcode()
        shelf = await _location(db, org_id, async_test_user.id, 'Loose Shelf')
        await _item(db, org_id, shelf, '3', name='Unlisted jam', barcode=barcode)
        await db.commit()

        result = await BarcodeScanProvider().handle(barcode, async_test_user, db)

        assert result is not None
        assert result.status == 'product_stock'
        assert result.stock_summary is not None
        assert result.stock_summary['total_quantity'] == 3.0

    async def test_a_code_nobody_has_is_still_a_new_product(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        result = await BarcodeScanProvider().handle(
            _barcode(), async_test_user, real_async_db_session
        )

        assert result is not None
        assert result.status == 'unassigned'
        # The line under the status is a catalogue key, not a sentence the
        # server wrote in English for every reader.
        assert result.message_key == 'scan:result.newProduct'
        assert result.message_params is None
