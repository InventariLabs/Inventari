"""A serial number typed into the scan form is a serial number that is saved.

The quick-add form after a scan renders the serial number field — it shares
the product form with the manual create — but the request schema behind it
had no such field, so the value was dropped on the way and the response
came back 200. Nothing told the reader their input had gone nowhere.

The same drop took the uniqueness rule with it: two assets could hold one
serial number as long as one of them arrived by scan.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.storage_location import LocationUsage, StorageLocation
from app.schemas.label_pool import LabelAssignRequest
from app.services.items.scan_service import assign_label_or_barcode

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


@pytest.mark.asyncio
class TestTheSerialNumberSurvivesTheScan:
    async def test_the_number_typed_on_the_form_lands_on_the_record(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _location(db, org_id, async_test_user.id, 'Main Warehouse')
        await db.commit()

        item = await assign_label_or_barcode(
            db,
            _barcode(),
            LabelAssignRequest(
                location_id=shelf.id,
                name='Drukarka',
                quantity=1,
                serial_number='SN-SCAN-0001',
            ),
            async_test_user,
        )
        await db.commit()

        assert item.serial_number == 'SN-SCAN-0001'

    async def test_the_uniqueness_rule_holds_on_this_door_too(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _location(db, org_id, async_test_user.id, 'Main Warehouse')
        await db.commit()

        await assign_label_or_barcode(
            db,
            _barcode(),
            LabelAssignRequest(
                location_id=shelf.id,
                name='Drukarka',
                quantity=1,
                serial_number='SN-SCAN-0002',
            ),
            async_test_user,
        )
        await db.commit()

        with pytest.raises(ValueError, match='SN-SCAN-0002'):
            await assign_label_or_barcode(
                db,
                _barcode(),
                LabelAssignRequest(
                    location_id=shelf.id,
                    name='Druga drukarka',
                    quantity=1,
                    serial_number='SN-SCAN-0002',
                ),
                async_test_user,
            )
        await db.rollback()

    async def test_a_form_without_the_field_still_works(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        """Most scans carry no serial — the field is optional, as on the form."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _location(db, org_id, async_test_user.id, 'Main Warehouse')
        await db.commit()

        item = await assign_label_or_barcode(
            db,
            _barcode(),
            LabelAssignRequest(
                location_id=shelf.id, name='Kawa', quantity=Decimal('1')
            ),
            async_test_user,
        )
        await db.commit()

        assert item.serial_number is None


@pytest.mark.asyncio
class TestTheOtherFieldsTheFormAsksFor:
    """The same drop, two fields over: the product form renders price
    and shelf after a scan, and the request carried none of them."""

    async def test_price_and_shelf_land_on_the_record(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _location(db, org_id, async_test_user.id, 'Main Warehouse')
        await db.commit()

        item = await assign_label_or_barcode(
            db,
            _barcode(),
            LabelAssignRequest(
                location_id=shelf.id,
                name='Drukarka',
                quantity=1,
                purchase_price=249.99,
                shelf_location='Regał B, półka 3',
            ),
            async_test_user,
        )
        await db.commit()

        assert item.purchase_price == Decimal('249.99')
        assert item.shelf_location == 'Regał B, półka 3'
