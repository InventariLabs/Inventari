"""A scanned product says exactly where each record stands and what of it is free.

The sheet listed each record under the shelf's own name, so two shelves called
"Shelf 1" in different racks looked alike, and nothing said that part of a
record was already promised to a document or which batch it belonged to. The
scan now carries the shelf's path and code, the batch, and the reserved and
free figures beside the quantity.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scan_providers import BarcodeScanProvider
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import LocationUsage, StorageLocation
from tests.integration._holds import hold_async
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


async def _location(
    db: AsyncSession, org_id, user_id, name: str, parent=None, short_code=None
) -> StorageLocation:
    location = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        name=name,
        parent_id=parent.id if parent else None,
        short_code=short_code,
        usage=LocationUsage.INTERNAL,
    )
    db.add(location)
    await db.flush()
    return location


@pytest.mark.asyncio
class TestTheScanSheetRows:
    async def test_scan_distinguishes_an_open_record_on_the_same_shelf(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        barcode = f'76{uuid.uuid4().int % 10**11:011d}'
        template = ProductTemplate(
            organization_id=org_id, name='Packs', barcode=barcode
        )
        db.add(template)
        await db.flush()
        shelf = await _location(db, org_id, async_test_user.id, 'Pantry')
        records = [
            Item(
                organization_id=org_id,
                storage_location_id=shelf.id,
                name='Packs',
                quantity=Decimal('1'),
                template_id=template.id,
                meta_data=metadata,
            )
            for metadata in (None, {'opened': {'at': '2026-10-15T10:00:00+00:00'}})
        ]
        db.add_all(records)
        await db.run_sync(anchor_pending_records)
        await db.commit()

        result = await BarcodeScanProvider().handle(barcode, async_test_user, db)

        assert result is not None and result.stock_summary is not None
        rows = {row['id']: row for row in result.stock_summary['items']}
        assert rows[str(records[0].id)]['opened_at'] is None
        assert rows[str(records[1].id)]['opened_at'] == '2026-10-15T10:00:00+00:00'

    async def test_a_record_carries_its_path_code_batch_and_reserved_figures(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        barcode = f'76{uuid.uuid4().int % 10**11:011d}'
        template = ProductTemplate(
            organization_id=org_id, name='Kawa mielona', barcode=barcode
        )
        db.add(template)
        await db.flush()
        warehouse = await _location(db, org_id, async_test_user.id, 'Warehouse')
        rack = await _location(db, org_id, async_test_user.id, 'Rack 4', warehouse)
        shelf = await _location(
            db, org_id, async_test_user.id, 'Shelf 2', rack, short_code='R4-S2'
        )
        lot = StockLot(
            organization_id=org_id,
            product_template_id=template.id,
            name='LOT-77',
        )
        db.add(lot)
        await db.flush()
        item = Item(
            organization_id=org_id,
            storage_location_id=shelf.id,
            name='Kawa mielona',
            quantity=Decimal('10'),
            template_id=template.id,
            lot_id=lot.id,
        )
        db.add(item)
        await db.run_sync(anchor_pending_records)
        await db.flush()
        await hold_async(db, _Grain(item), Decimal('4'))
        await db.commit()

        result = await BarcodeScanProvider().handle(barcode, async_test_user, db)

        assert result is not None and result.stock_summary is not None
        [row] = result.stock_summary['items']
        assert row['location'] == 'Shelf 2'
        assert row['location_path'] == 'Warehouse → Rack 4 → Shelf 2'
        assert row['location_code'] == 'R4-S2'
        assert row['lot'] == 'LOT-77'
        assert row['reserved_quantity'] == 4.0
        assert row['available_quantity'] == 6.0

    async def test_a_record_with_no_batch_or_hold_says_so_plainly(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        barcode = f'76{uuid.uuid4().int % 10**11:011d}'
        template = ProductTemplate(
            organization_id=org_id, name='Herbata', barcode=barcode
        )
        db.add(template)
        await db.flush()
        shelf = await _location(db, org_id, async_test_user.id, 'Pantry')
        db.add(
            Item(
                organization_id=org_id,
                storage_location_id=shelf.id,
                name='Herbata',
                quantity=Decimal('3'),
                template_id=template.id,
            )
        )
        await db.run_sync(anchor_pending_records)
        await db.commit()

        result = await BarcodeScanProvider().handle(barcode, async_test_user, db)

        assert result is not None and result.stock_summary is not None
        [row] = result.stock_summary['items']
        assert row['location_path'] == 'Pantry'
        assert row['location_code'] is None
        assert row['lot'] is None
        assert row['reserved_quantity'] == 0.0
        assert row['available_quantity'] == 3.0

    async def test_a_hold_is_split_across_the_records_of_its_group(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        """One hold of 4 over records of 3 and 5 reads 4 once, never twice.

        A receipt with another use-by date lands as its own record in the
        same group; the reservation names the group, so each record used to
        show the whole 4 and the first one a free figure of -1.
        """
        db = real_async_db_session
        org_id = async_test_user.organization_id
        barcode = f'76{uuid.uuid4().int % 10**11:011d}'
        template = ProductTemplate(
            organization_id=org_id, name='Mleko', barcode=barcode
        )
        db.add(template)
        await db.flush()
        shelf = await _location(db, org_id, async_test_user.id, 'Fridge')
        landed = datetime.now(UTC)
        records = [
            Item(
                organization_id=org_id,
                storage_location_id=shelf.id,
                name='Mleko',
                quantity=Decimal(quantity),
                template_id=template.id,
                created_at=landed + timedelta(minutes=minutes),
            )
            for quantity, minutes in (('3', 0), ('5', 1))
        ]
        db.add_all(records)
        await db.run_sync(anchor_pending_records)
        await db.flush()
        await hold_async(db, _Grain(records[0]), Decimal('4'))
        await db.commit()

        result = await BarcodeScanProvider().handle(barcode, async_test_user, db)

        assert result is not None and result.stock_summary is not None
        rows = {r['id']: r for r in result.stock_summary['items']}
        first, second = (rows[str(r.id)] for r in records)
        # A draw empties the older record first, so the hold sits on the newer.
        assert (first['reserved_quantity'], first['available_quantity']) == (0.0, 3.0)
        assert (second['reserved_quantity'], second['available_quantity']) == (
            4.0,
            1.0,
        )


class _Grain:
    """The key of an item's group, as ``hold_async`` reads it."""

    def __init__(self, item: Item) -> None:
        self.organization_id = item.organization_id
        self.product_template_id = item.template_id
        self.storage_location_id = item.storage_location_id
        self.lot_id = item.lot_id
        self.owner_id = item.owner_id
