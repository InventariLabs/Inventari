"""Integration tests for ProductTemplate.removal_strategy wiring.

The pure-function resolver is tested in
``tests/unit/test_remove_strategy_resolver.py``, and the order a draw takes
the product's own strategy in — earliest date first under FEFO, oldest
record first under FIFO — in ``test_stock_is_taken_from_every_shelf_in_order``.
This pins the one thing left: an explicit ``removal_strategy`` handed to
the draw (``take_from_the_records_async``) wins over the template's.

The draw is planned from the records, so each lot stands in a record put on
the shelf the way the application puts it there.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.core.public_api import core_api
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from tests.integration._shelf import put_on_shelf


@pytest.mark.integration
@pytest.mark.asyncio
class TestTemplateRemovalStrategyEndToEnd:
    """The strategy a caller names drives the draw over the template's."""

    async def test_explicit_override_wins_over_template(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        """Caller override trumps ProductTemplate.removal_strategy."""
        db = real_async_db_session
        org_id = async_test_household.id
        location_id = async_test_storage_location.id

        # Template says FEFO, but caller passes FIFO explicitly.
        template = ProductTemplate(
            organization_id=org_id,
            name=f'Override Template {uuid4().hex[:6]}',
            sku=f'SKU-OVR-{uuid4().hex[:8]}',
            removal_strategy='FEFO',
        )
        db.add(template)
        await db.flush()

        # The older record carries the later date, so FEFO and FIFO answer
        # differently — which is the point. Counted from today: stock past
        # its date is held back from the draw.
        today = datetime.now(UTC).date()
        lot_p = StockLot(
            organization_id=org_id,
            product_template_id=template.id,
            name='Lot P',
            use_by_date=today + timedelta(days=300),
        )
        lot_q = StockLot(
            organization_id=org_id,
            product_template_id=template.id,
            name='Lot Q',
            use_by_date=today + timedelta(days=30),
        )
        db.add_all([lot_p, lot_q])
        await db.flush()

        now = datetime.now(UTC)
        for lot, created_at in ((lot_p, now - timedelta(days=10)), (lot_q, now)):
            record = await put_on_shelf(
                db, async_test_user, template, location_id, 4, lot_id=lot.id
            )
            await db.execute(
                update(Item).where(Item.id == record.id).values(created_at=created_at)
            )
        await db.commit()

        # The control: without an override the template's FEFO takes Q.
        control = await core_api.stock.take_from_the_records_async(
            db, org_id, template.id, location_id, Decimal('1')
        )
        assert {row.lot_id: row.consumed for row in control} == {lot_q.id: Decimal('1')}

        # Override to FIFO → consume the oldest record first.
        breakdown = await core_api.stock.take_from_the_records_async(
            db,
            org_id,
            template.id,
            location_id,
            Decimal('4'),
            removal_strategy='FIFO',
        )
        await db.commit()

        consumed_by_lot = {row.lot_id: row.consumed for row in breakdown}
        assert consumed_by_lot == {lot_p.id: Decimal('4')}
