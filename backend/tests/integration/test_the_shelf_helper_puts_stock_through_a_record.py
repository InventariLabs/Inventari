"""The shelf a test builds with ``put_on_shelf`` is one the application could build.

Record, the shelf as the records' view sums it, movement and cost layer
agree, and the reconciliation finds nothing between the shelf, the ledger
and the layers — which is what stock constructed by hand cannot say for
itself.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.testing import ShelfRow
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.services.analytics.reconciliation import get_reconciliation_async
from tests.integration._shelf import put_on_shelf, shelf_keeper

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pantry(real_async_db_session):
    db = real_async_db_session
    org = Organization(name=f'Pantry {uuid4().hex[:6]}', enabled_modules=['core'])
    db.add(org)
    await db.flush()
    keeper = await shelf_keeper(db, org.id)
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    shelf = StorageLocation(
        name='Shelf',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=keeper.id,
    )
    flour = ProductTemplate(name='Rye flour', organization_id=org.id)
    db.add_all([shelf, flour])
    await db.flush()
    lot = StockLot(organization_id=org.id, product_template_id=flour.id, name='L-1')
    db.add(lot)
    await db.flush()
    return db, keeper, shelf, flour, lot


async def _on_shelf(db, flour, shelf, lot):
    return await db.scalar(
        select(ShelfRow.quantity).where(
            ShelfRow.product_template_id == flour.id,
            ShelfRow.storage_location_id == shelf.id,
            ShelfRow.lot_id == lot.id,
        )
    )


async def test_the_record_the_shelf_the_move_and_the_layer_agree(pantry):
    db, keeper, shelf, flour, lot = pantry

    item = await put_on_shelf(db, keeper, flour, shelf.id, '5', lot_id=lot.id)
    await db.commit()

    assert (item.template_id, item.lot_id, item.quantity) == (
        flour.id,
        lot.id,
        Decimal('5'),
    )
    assert await _on_shelf(db, flour, shelf, lot) == Decimal('5')
    moved_in = await db.scalar(
        select(func.sum(StockMove.quantity)).where(
            StockMove.product_template_id == flour.id,
            StockMove.to_location_id == shelf.id,
        )
    )
    assert moved_in == Decimal('5')
    layered = await db.scalar(
        select(func.sum(StockValuationLayer.remaining_qty)).where(
            StockValuationLayer.product_template_id == flour.id
        )
    )
    assert layered == Decimal('5')


async def test_a_second_record_adds_to_the_same_shelf_and_nothing_drifts(pantry):
    db, keeper, shelf, flour, lot = pantry

    await put_on_shelf(db, keeper, flour, shelf.id, 5, lot_id=lot.id)
    await put_on_shelf(
        db, keeper, flour, shelf.id, 3, lot_id=lot.id, purchase_price='2.50'
    )
    await db.commit()

    assert await _on_shelf(db, flour, shelf, lot) == Decimal('8')
    report = await get_reconciliation_async(db, keeper.organization_id)
    assert (
        report.quant_move_drift_count,
        report.layer_quant_drift_count,
    ) == (0, 0)
