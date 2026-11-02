"""A record born of a scan says who scanned it.

The scan wrote its own ``ItemHistory`` rows by hand: the author's id went
into ``changes['created_by']`` and the ``user_id`` column stayed NULL. The
history screen reads the column — ``user_name`` comes from the related user
— so a scanned record's history named nobody, while the same record made by
hand through the form carried its author. Both scan entries now go through
the one history helper, which fills the column.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.label_pool import LabelPool
from app.models.storage_location import LocationUsage, StorageLocation
from app.schemas.label_pool import LabelAssignRequest
from app.services.items.scan_service import assign_label_or_barcode
from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


def _user_dto(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id,
        organization_id=user.organization_id,
        role=user.role,
        email=user.email,
    )


def _barcode() -> str:
    return f'76{uuid.uuid4().int % 10**11:011d}'


async def _shelf(db: AsyncSession, org_id, user_id) -> StorageLocation:
    shelf = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        name='Scan History Shelf',
        usage=LocationUsage.INTERNAL,
    )
    db.add(shelf)
    await db.flush()
    return shelf


async def _label(db: AsyncSession, org_id, user_id) -> LabelPool:
    label = LabelPool(
        short_code=f'STM-H{uuid.uuid4().hex[:5].upper()}',
        organization_id=org_id,
        created_by=user_id,
    )
    db.add(label)
    await db.flush()
    return label


async def _history(db: AsyncSession, item_id, action: str) -> ItemHistory | None:
    return (
        await db.scalars(
            select(ItemHistory).where(
                ItemHistory.item_id == item_id,
                ItemHistory.action == action,
            )
        )
    ).first()


@pytest.mark.asyncio
class TestTheScanSignsItsHistory:
    async def test_a_scanned_record_signs_its_history(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _shelf(db, org_id, async_test_user.id)
        label = await _label(db, org_id, async_test_user.id)
        await db.commit()

        item = await assign_label_or_barcode(
            db,
            label.short_code,
            LabelAssignRequest(
                location_id=shelf.id,
                name='Scanned with a name',
                quantity=1,
            ),
            _user_dto(async_test_user),
        )
        await db.commit()

        entry = await _history(db, item.id, 'CREATED_VIA_SCAN')
        assert entry is not None
        assert entry.user_id == async_test_user.id
        assert 'created_by' not in (entry.changes or {})

    async def test_a_scan_that_grew_a_record_signs_its_history(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        """The quantity-increase entry carries the scanner too — it was
        written by the same hand and left the same column empty."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _shelf(db, org_id, async_test_user.id)
        barcode = _barcode()
        existing = Item(
            name='Known product',
            organization_id=org_id,
            storage_location_id=shelf.id,
            quantity=1,
            barcode=barcode,
        )
        db.add(existing)
        await db.commit()

        item = await assign_label_or_barcode(
            db,
            barcode,
            LabelAssignRequest(
                location_id=shelf.id,
                name='Known product',
                quantity=2,
            ),
            _user_dto(async_test_user),
        )
        await db.commit()

        assert item.id == existing.id
        entry = await _history(db, item.id, 'QUANTITY_INCREASED_VIA_SCAN')
        assert entry is not None
        assert entry.user_id == async_test_user.id
        assert 'created_by' not in (entry.changes or {})

    async def test_the_history_screen_names_the_scanner(
        self, real_async_client, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _shelf(db, org_id, async_test_user.id)
        label = await _label(db, org_id, async_test_user.id)
        await db.commit()

        item = await assign_label_or_barcode(
            db,
            label.short_code,
            LabelAssignRequest(
                location_id=shelf.id,
                name='Scanned for the screen',
                quantity=1,
            ),
            _user_dto(async_test_user),
        )
        await db.commit()

        response = await real_async_client.get(
            f'/api/v1/items/{item.id}/history', headers=_auth(async_test_user)
        )

        assert response.status_code == 200, response.text
        entry = next(
            row
            for row in response.json()['items']
            if row['action'] == 'CREATED_VIA_SCAN'
        )
        assert entry['user_name'] == (
            async_test_user.full_name or async_test_user.email
        )
