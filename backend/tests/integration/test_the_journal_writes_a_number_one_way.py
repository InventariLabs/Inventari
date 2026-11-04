"""The same quantity, changed two ways, has to read the same in the journal.

One rule was written down twice and implemented once. `docs/subsystems/AUDIT.md`
says a snapshot carries the exact Decimals as strings -- "the trace must not be
the least precise copy of the facts" -- and the single-item path was changed to
match. Everything going through `audit_value` kept turning a Decimal into a
float, so the same field on the same product read `"12.500"` when somebody
edited it alone and `12.5` when the same edit went through the batch screen.

Two functions now, because the two uses were never the same thing:
`audit_value` says what a value became and `audit_key` decides whether it
moved at all. Comparing exact digits is what made `Decimal('1.000')` and the
`1` a form posts look like a change, which is the reason the float was there
in the first place.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.contracts import UserContextDTO
from app.models.audit_log import AuditLog
from app.schemas.item import ItemBulkUpdate, ItemUpdate
from app.services.items import bulk_update_items, update_item

pytestmark = pytest.mark.integration


async def _snapshots(db, item_id) -> list[dict]:
    rows = await db.scalars(
        select(AuditLog)
        .where(AuditLog.target_id == item_id, AuditLog.action == 'UPDATE')
        .order_by(AuditLog.created_at.asc())
    )
    return [row.snapshot or {} for row in rows.all()]


class TestOneShapeForOneNumber:
    async def test_single_and_bulk_edits_write_the_quantity_alike(
        self, real_async_db_session, async_test_item, async_test_user
    ):
        db = real_async_db_session
        await update_item(db, async_test_item, ItemUpdate(quantity=5), async_test_user)
        await bulk_update_items(
            db,
            ItemBulkUpdate(
                item_ids=[async_test_item.id],
                update_data=ItemUpdate(quantity=7),
            ),
            UserContextDTO(
                id=async_test_user.id,
                organization_id=async_test_user.organization_id,
            ),
        )
        await db.flush()

        # The record predates its card, so the first edit also adopted one and
        # left the journal row that says so. The rows this test compares are
        # the ones that carry a quantity.
        quantity_rows = [
            snapshot
            for snapshot in await _snapshots(db, async_test_item.id)
            if 'quantity' in (snapshot.get('after') or {})
        ]
        single, batch = quantity_rows
        assert isinstance(single['after']['quantity'], str)
        assert isinstance(batch['after']['quantity'], str)
        assert Decimal(single['after']['quantity']) == 5
        assert Decimal(batch['after']['quantity']) == 7

    async def test_the_exact_digits_survive(
        self, real_async_db_session, async_test_item, async_test_user
    ):
        """A float is a less precise copy of the money it describes."""
        db = real_async_db_session
        await update_item(
            db,
            async_test_item,
            ItemUpdate(purchase_price=Decimal('19.99')),
            async_test_user,
        )
        await db.flush()

        (snapshot,) = await _snapshots(db, async_test_item.id)
        assert snapshot['after']['purchase_price'] == '19.99'

    async def test_a_form_that_posts_the_same_quantity_differently_is_no_change(
        self, real_async_db_session, async_test_item, async_test_user
    ):
        """`Decimal('2.000')` and the `2` a form sends are one quantity.

        This is what the float was protecting, and it must keep holding now
        that the value written down is the exact digits.
        """
        db = real_async_db_session
        await update_item(db, async_test_item, ItemUpdate(quantity=2), async_test_user)
        await db.flush()

        assert await _snapshots(db, async_test_item.id) == []


class TestTheLowStockThresholdReadsLikeTheOtherNumbers:
    """`min_quantity` is a DOUBLE column, but the journal is not its mirror.

    The column keeps a float; what the journal writes is the digits that were
    typed. A float in the snapshot is a number to the audit screen, which
    prints it at six significant digits: 1234.567 read 1234.57.
    """

    async def test_an_item_edit_writes_the_threshold_as_digits(
        self, real_async_db_session, async_test_item, async_test_user
    ):
        db = real_async_db_session
        await update_item(
            db,
            async_test_item,
            ItemUpdate(min_quantity=Decimal('1234.567')),
            async_test_user,
        )
        await db.flush()

        (snapshot,) = [
            s
            for s in await _snapshots(db, async_test_item.id)
            if 'min_quantity' in (s.get('after') or {})
        ]
        assert snapshot['after']['min_quantity'] == '1234.567'
        assert isinstance(snapshot['before']['min_quantity'], str)

    async def test_the_same_threshold_with_other_digits_writes_nothing(
        self, real_async_db_session, async_test_item, async_test_user
    ):
        db = real_async_db_session
        await update_item(
            db, async_test_item, ItemUpdate(min_quantity=Decimal('3')), async_test_user
        )
        await db.flush()
        before = len(await _snapshots(db, async_test_item.id))

        await update_item(
            db,
            async_test_item,
            ItemUpdate(min_quantity=Decimal('3.000')),
            async_test_user,
        )
        await db.flush()

        assert len(await _snapshots(db, async_test_item.id)) == before

    def test_the_record_and_the_comparison_read_a_float_two_ways(self):
        from app.services.audit_service import audit_key, audit_value

        assert audit_value(1234.567) == '1234.567'
        assert audit_value({'min_quantity': 0.0}) == {'min_quantity': '0.0'}
        # The comparison still sees a number, so a resave stays silent.
        assert audit_key(1234.567) == audit_key(Decimal('1234.567000')) == 1234.567
