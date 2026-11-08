"""Tests for item lifecycle operations (consume/discard/restore/transfer).

The dead CoreAPI lifecycle mixin (``core_api.items.consume_async`` /
``discard_async`` / ``restore_async`` / ``transfer_async``) was removed
as dead code; the live paths are:

- ``app.services.items.consume_item`` / ``discard_item`` / ``restore_item``
  (service functions, take a loaded ``Item``)
- ``core_api.items.transfer_async`` (the live facade method, org-scoped,
  returns ``ItemDTO | None``)

These tests pin the same behaviour against those live entry points.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.contracts import UserContextDTO
from app.core.public_api import core_api
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.schemas.item import ItemConsumeRequest, ItemDiscardRequest
from app.services.items import consume_item, discard_item, restore_item

from ._core_api_helpers import make_other_org

pytestmark = pytest.mark.integration


async def _make_item(
    db, organization_id, storage_location_id, *, name: str, quantity: Decimal
) -> Item:
    def _create(s: Session) -> Item:
        item = Item(
            organization_id=organization_id,
            storage_location_id=storage_location_id,
            name=name,
            quantity=quantity,
        )
        s.add(item)
        s.commit()
        s.refresh(item)
        return item

    return await db.run_sync(_create)


async def _make_second_location(db, organization_id, *, created_by) -> StorageLocation:
    from app.models.storage_type import StorageType

    def _create(s: Session) -> StorageLocation:
        st = s.scalars(
            select(StorageType).where(StorageType.type_code == 'SHELF')
        ).first()
        if st is None:
            st = StorageType(name='Shelf', type_code='SHELF')
            s.add(st)
            s.commit()
        loc = StorageLocation(
            organization_id=organization_id,
            name='Destination',
            storage_type_id=st.id,
            created_by=created_by,
        )
        s.add(loc)
        s.commit()
        s.refresh(loc)
        return loc

    return await db.run_sync(_create)


def _ctx_for(user) -> UserContextDTO:
    """Build a UserContextDTO from a User fixture."""
    return UserContextDTO(
        id=user.id,
        organization_id=user.organization_id,
        role=user.role,
        email=user.email,
    )


@pytest.mark.asyncio
class TestItemLifecycleOperations:
    """consume / discard / restore / transfer via the live entry points."""

    async def test_consume_reduces_quantity(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        """consume_item(quantity=3) → item.quantity -= 3."""
        db = real_async_db_session
        item = await _make_item(
            db,
            async_test_household.id,
            async_test_storage_location.id,
            name='Milk',
            quantity=Decimal('10'),
        )

        result = await consume_item(
            db,
            item=item,
            consume_data=ItemConsumeRequest(quantity=Decimal('3'), reason='USED'),
            user=_ctx_for(async_test_user),
        )
        await db.commit()

        assert isinstance(result, Item)
        assert result.quantity == Decimal('7')
        assert result.id == item.id

    async def test_discard_reduces_quantity(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        """discard_item(quantity=2) → item.quantity -= 2."""
        db = real_async_db_session
        item = await _make_item(
            db,
            async_test_household.id,
            async_test_storage_location.id,
            name='Yogurt',
            quantity=Decimal('5'),
        )

        result = await discard_item(
            db,
            item=item,
            discard_data=ItemDiscardRequest(quantity=Decimal('2'), reason='expired'),
            user=_ctx_for(async_test_user),
        )
        await db.commit()

        assert result.quantity == Decimal('3')

    async def test_transfer_moves_to_new_location(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        """transfer → item.storage_location_id == new location."""
        db = real_async_db_session
        item = await _make_item(
            db,
            async_test_household.id,
            async_test_storage_location.id,
            name='Butter',
            quantity=Decimal('4'),
        )
        new_loc = await _make_second_location(
            db, async_test_household.id, created_by=async_test_user.id
        )

        result = await core_api.items.transfer_async(
            db,
            async_test_household.id,
            item.id,
            new_loc.id,
            user_id=async_test_user.id,
        )
        await db.commit()

        assert result is not None
        assert result.location_id == new_loc.id

    async def test_transfer_rejects_item_from_other_org(
        self,
        real_async_db_session,
        async_test_user,
        async_test_storage_location,
    ):
        """Looking up item in wrong org → None (facade is org-scoped)."""
        db = real_async_db_session
        other_org = await db.run_sync(make_other_org)
        # Use the same storage_location (cross-org is OK for storage, items are org-scoped)
        item = await _make_item(
            db,
            other_org.id,
            async_test_storage_location.id,
            name='Cross',
            quantity=Decimal('10'),
        )
        # Even though async_test_user is in their own org, we look up item by other org id
        result = await core_api.items.transfer_async(
            db,
            async_test_user.organization_id,
            item.id,
            async_test_storage_location.id,
            user_id=async_test_user.id,
        )
        assert result is None

    async def test_consume_overdraw_raises(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        """Consuming more than current quantity raises ValueError."""
        db = real_async_db_session
        item = await _make_item(
            db,
            async_test_household.id,
            async_test_storage_location.id,
            name='Egg',
            quantity=Decimal('1'),
        )

        with pytest.raises(ValueError):
            await consume_item(
                db,
                item=item,
                consume_data=ItemConsumeRequest(quantity=Decimal('5'), reason='USED'),
                user=_ctx_for(async_test_user),
            )

    async def test_transfer_rejects_unknown_destination(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        """Transfer to a non-existent location → NotFoundException (404)."""
        from app.core.exceptions import NotFoundException

        db = real_async_db_session
        item = await _make_item(
            db,
            async_test_household.id,
            async_test_storage_location.id,
            name='Bread',
            quantity=Decimal('2'),
        )

        with pytest.raises(NotFoundException):
            await core_api.items.transfer_async(
                db,
                async_test_household.id,
                item.id,
                uuid4(),  # non-existent
                user_id=async_test_user.id,
            )

    async def test_restore_unmarks_soft_deleted(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        """restore_item → is_deleted = False, quantity restored from history."""
        from app.services.items._lifecycle import delete_item

        db = real_async_db_session
        item = await _make_item(
            db,
            async_test_household.id,
            async_test_storage_location.id,
            name='RestoreMe',
            quantity=Decimal('5'),
        )
        ctx = _ctx_for(async_test_user)

        # Soft delete via existing service
        await delete_item(db, item, ctx, reason='OTHER')
        await db.commit()

        # Verify deleted
        def _refresh(s: Session) -> Item:
            return s.get(Item, item.id)

        refreshed = await db.run_sync(_refresh)
        assert refreshed.is_deleted is True

        # The deletion keeps the quantity as its exact digits (AUDIT.md), and
        # the restore reads it back from that shape.
        def _deleted_entry(s: Session) -> dict:
            from app.models.item_history import ItemHistory

            return s.scalars(
                select(ItemHistory.changes).where(
                    ItemHistory.item_id == item.id, ItemHistory.action == 'DELETED'
                )
            ).one()

        changes = await db.run_sync(_deleted_entry)
        assert isinstance(changes['old_quantity'], str)
        assert Decimal(changes['old_quantity']) == Decimal('5')

        # Restore via the service
        result = await restore_item(db, item=item, user=ctx)
        await db.commit()

        assert result.is_deleted is False
        assert result.quantity == Decimal('5')

    async def test_soft_delete_without_a_reason_keeps_none(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        """An archive that names no why stores no why, through the facade too.

        The HTTP DELETE and this one are two doors onto the same write, and
        the facade's default used to answer the absence with ``OTHER`` — so
        an archive made by a module read "Status: Other" on the sheet the
        same way the one made from the list did.
        """
        db = real_async_db_session
        item = await _make_item(
            db,
            async_test_household.id,
            async_test_storage_location.id,
            name='NoReasonOnFile',
            quantity=Decimal('3'),
        )
        ctx = _ctx_for(async_test_user)

        deleted = await core_api.items.soft_delete_async(
            db, async_test_household.id, item.id, ctx
        )
        await db.commit()

        assert deleted is True
        refreshed = await db.run_sync(lambda s: s.get(Item, item.id))
        assert refreshed.is_deleted is True
        assert refreshed.deletion_reason is None

    async def test_discard_returns_orm_item(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
        async_test_storage_location,
    ):
        """discard_item returns the ORM Item."""
        db = real_async_db_session
        item = await _make_item(
            db,
            async_test_household.id,
            async_test_storage_location.id,
            name='Cheese',
            quantity=Decimal('3'),
        )

        result = await discard_item(
            db,
            item=item,
            discard_data=ItemDiscardRequest(quantity=Decimal('1'), reason='damaged'),
            user=_ctx_for(async_test_user),
        )
        await db.commit()

        assert isinstance(result, Item)
        assert result.name == 'Cheese'
        assert result.quantity == Decimal('2')
