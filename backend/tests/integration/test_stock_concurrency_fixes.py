"""Integration tests for stock-consistency fixes.

Covers the logic-level behaviour of:
- delete_item releases reservations before zeroing quantity.
- move_item refuses to move reserved stock + same-location no-op.
- bulk_update_items moves the stock on a storage_location-only change.

The concurrency-level half — writers of one group of stock waiting for each
other — is the anchor lock's, and is tested beside it.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from ._core_api_helpers import make_user_context
from ._shelf import put_on_shelf


async def _second_location(
    db: AsyncSession, org_id: UUID, storage_type_id: UUID, name: str, user_id: UUID
):
    """Create a second storage location sharing the storage type."""
    from app.models.storage_location import StorageLocation

    loc = StorageLocation(
        name=name,
        organization_id=org_id,
        storage_type_id=storage_type_id,
        created_by=user_id,
    )
    db.add(loc)
    await db.flush()
    return loc


@pytest.mark.integration
@pytest.mark.asyncio
class TestMoveItemGuards:
    """``move_item`` must refuse reserved stock and treat same-location
    as a no-op."""

    async def test_move_to_same_location_is_noop(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_item,
        async_test_user,
    ) -> None:
        """Moving an item to its current location must not touch the stock."""
        from app.schemas.item import ItemMove
        from app.services.items import move_item

        db = real_async_db_session
        org_id = async_test_household.id
        item = async_test_item
        same_loc = async_test_storage_location.id

        user_ctx = make_user_context(org_id, async_test_user.id)
        before = item.quantity
        await move_item(
            db,
            item,
            ItemMove(to_location_id=same_loc),
            user=user_ctx,
            post_the_change=False,
        )
        await db.refresh(item)
        assert item.quantity == before
        assert item.storage_location_id == same_loc

    async def test_move_refuses_when_source_has_reservation(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ) -> None:
        """Moving an item whose source shelf is held by a reservation must
        raise, not silently drain the reservation."""
        from app.schemas.item import ItemMove
        from app.services.items import move_item

        db = real_async_db_session
        org_id = async_test_household.id

        from ._core_api_helpers import make_template

        template = await db.run_sync(lambda s: make_template(s, org_id))
        loc_b = await _second_location(
            db,
            org_id,
            async_test_storage_location.storage_type_id,
            'Loc B',
            async_test_user.id,
        )
        item = await put_on_shelf(
            db, async_test_user, template, async_test_storage_location.id, 5
        )
        await core_api.stock.reserve_for_document_async(
            db,
            organization_id=org_id,
            product_template_id=template.id,
            location_id=async_test_storage_location.id,
            needed_qty=Decimal('3'),
            document_id=UUID(int=0),
        )
        await db.commit()

        user_ctx = make_user_context(org_id, async_test_user.id)
        with pytest.raises(ValueError, match='reservation'):
            await move_item(
                db,
                item,
                ItemMove(to_location_id=loc_b.id),
                user=user_ctx,
            )


@pytest.mark.integration
@pytest.mark.asyncio
class TestBulkUpdateStorageLocation:
    """A storage_location-only bulk update must move the stock with the record."""

    async def test_bulk_location_move_syncs_quant(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ) -> None:
        from app.schemas.item import ItemBulkUpdate, ItemUpdate
        from app.services.items import bulk_update_items

        from ._core_api_helpers import make_template

        db = real_async_db_session
        org_id = async_test_household.id

        template = await db.run_sync(lambda s: make_template(s, org_id))
        loc_b = await _second_location(
            db,
            org_id,
            async_test_storage_location.storage_type_id,
            'Bulk B',
            async_test_user.id,
        )
        item = await put_on_shelf(
            db, async_test_user, template, async_test_storage_location.id, 10
        )
        await db.commit()

        user_ctx = make_user_context(org_id, async_test_user.id)
        await bulk_update_items(
            db,
            ItemBulkUpdate(
                item_ids=[item.id],
                update_data=ItemUpdate(location_id=loc_b.id),
            ),
            user_ctx,
        )

        quants_a = await core_api.stock.list_quants_async(
            db,
            organization_id=org_id,
            product_template_id=template.id,
            storage_location_id=async_test_storage_location.id,
        )
        quants_b = await core_api.stock.list_quants_async(
            db,
            organization_id=org_id,
            product_template_id=template.id,
            storage_location_id=loc_b.id,
        )
        assert sum(q.quantity for q in quants_a) == 0
        assert sum(q.quantity for q in quants_b) == 10


@pytest.mark.integration
@pytest.mark.asyncio
class TestDeleteItemReleasesReservations:
    """``delete_item`` releases reservations before zeroing quantity."""

    async def test_delete_item_with_reservation_succeeds(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
        async_test_user,
    ) -> None:
        """An item whose stock has a reservation must still be deletable; the
        reservation is released first instead of raising 'Insufficient stock'."""
        from app.services.items import delete_item

        from ._core_api_helpers import make_template

        db = real_async_db_session
        org_id = async_test_household.id

        template = await db.run_sync(lambda s: make_template(s, org_id))
        item = await put_on_shelf(
            db, async_test_user, template, async_test_storage_location.id, 5
        )
        await core_api.stock.reserve_for_document_async(
            db,
            organization_id=org_id,
            product_template_id=template.id,
            location_id=async_test_storage_location.id,
            needed_qty=Decimal('3'),
            document_id=UUID(int=1),
        )
        await db.commit()

        user_ctx = make_user_context(org_id, async_test_user.id)
        # Must not raise 'Insufficient available stock'.
        await delete_item(db, item, user_ctx, reason='DAMAGED')
        assert item.is_deleted is True
        assert item.quantity == 0
