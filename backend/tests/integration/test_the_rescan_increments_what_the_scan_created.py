"""A second scan of one code adds to the record the first scan created.

The code a scan carries lives on the product's catalogue row while the
record stays bare (``_product_code`` made that one decision for every
door), but the increment lookup still asked ``Item.barcode`` alone — and
the record it minted answers nothing there. A rescan of the same code to
the same shelf therefore found no match and minted a second record of the
same product instead of bumping the first, measured on the live API with
the third assign of one code creating a new row at quantity 1.

The lookup now asks both carriers, the way the typed search does.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PeriodClosedError
from app.models.item import Item
from app.models.storage_location import LocationUsage, StorageLocation
from app.modules.warehouse.inventory_period_service import close_period
from app.schemas.label_pool import LabelAssignRequest
from app.services.items.scan_service import assign_label_or_barcode
from app.services.token_service import create_access_token

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
class TestTheRescanIncrementsWhatTheScanCreated:
    async def test_a_second_scan_of_one_code_bumps_the_first_record(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _location(db, org_id, async_test_user.id, 'Main Warehouse')
        await db.commit()
        code = _barcode()

        first = await assign_label_or_barcode(
            db,
            code,
            LabelAssignRequest(location_id=shelf.id, name='Kawa mielona', quantity=1),
            async_test_user,
        )
        await db.commit()

        # The record the scan minted wears no code of its own — the
        # catalogue row holds it. This is the state every rescan meets.
        assert first.barcode is None
        assert first.template_id is not None

        second = await assign_label_or_barcode(
            db,
            code,
            LabelAssignRequest(location_id=shelf.id, name='Kawa mielona', quantity=1),
            async_test_user,
        )
        await db.commit()
        await db.refresh(second, ['template'])

        assert second.id == first.id
        assert second.quantity == Decimal('2')
        rows = (
            await db.scalars(
                select(func.count())
                .select_from(Item)
                .where(
                    Item.storage_location_id == shelf.id,
                    Item.is_deleted.is_(False),
                )
            )
        ).one()
        assert rows == 1

    async def test_a_code_on_the_record_itself_is_still_matched(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        """Legacy rows keep the code on the record — the lookup asks both carriers."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _location(db, org_id, async_test_user.id, 'Legacy Shelf')
        await db.commit()
        code = _barcode()

        first = await assign_label_or_barcode(
            db,
            code,
            LabelAssignRequest(location_id=shelf.id, name='Mąka żytnia', quantity=1),
            async_test_user,
        )
        await db.commit()
        # Force the legacy carrier: the code on the record, none on the row's template.
        first.barcode = code
        first.template.barcode = None
        await db.commit()

        second = await assign_label_or_barcode(
            db,
            code,
            LabelAssignRequest(location_id=shelf.id, name='Mąka żytnia', quantity=1),
            async_test_user,
        )
        await db.commit()

        assert second.id == first.id
        assert second.quantity == Decimal('2')

    async def test_a_different_shelf_still_gets_its_own_record(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf_a = await _location(db, org_id, async_test_user.id, 'Shelf A')
        shelf_b = await _location(db, org_id, async_test_user.id, 'Shelf B')
        await db.commit()
        code = _barcode()

        first = await assign_label_or_barcode(
            db,
            code,
            LabelAssignRequest(location_id=shelf_a.id, name='Cukier', quantity=1),
            async_test_user,
        )
        second = await assign_label_or_barcode(
            db,
            code,
            LabelAssignRequest(location_id=shelf_b.id, name='Cukier', quantity=1),
            async_test_user,
        )
        await db.commit()

        assert second.id != first.id
        rows = (
            await db.scalars(
                select(func.count())
                .select_from(Item)
                .where(
                    Item.organization_id == org_id,
                    Item.is_deleted.is_(False),
                )
            )
        ).one()
        assert rows == 2

    async def test_a_rescan_never_lands_on_a_row_wearing_another_code(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        """Two codes of one product share a shelf; each keeps its own record.

        The order the branch first shipped preferred *any* row wearing a code
        over a bare one, so a rescan of A climbed onto the row wearing B:
        measured as four scans of A taking B's record from 2 to 6 while the
        record A itself created stayed at 1. The scanned code outranks a bare
        row, and a bare row outranks a row wearing a different code.
        """
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _location(db, org_id, async_test_user.id, 'Shared Shelf')
        await db.commit()
        code_a = _barcode()
        code_b = _barcode()

        scanned = await assign_label_or_barcode(
            db,
            code_a,
            LabelAssignRequest(location_id=shelf.id, name='Napój', quantity=1),
            async_test_user,
        )
        await db.commit()
        await db.refresh(scanned, ['template'])

        wearing_b = Item(
            organization_id=org_id,
            storage_location_id=shelf.id,
            template_id=scanned.template_id,
            name='Napój',
            quantity=Decimal('1'),
            barcode=code_b,
        )
        db.add(wearing_b)
        await db.commit()

        again = await assign_label_or_barcode(
            db,
            code_a,
            LabelAssignRequest(location_id=shelf.id, name='Napój', quantity=1),
            async_test_user,
        )
        await db.commit()
        await db.refresh(again)
        await db.refresh(wearing_b)

        assert again.id == scanned.id, (
            'the rescan bumps the record the scan created, not the row that '
            'wears the other code of the same product'
        )
        assert again.quantity == Decimal('2')
        assert wearing_b.quantity == Decimal('1'), (
            'a row wearing another code never takes the increment while a '
            'better candidate stands on the shelf'
        )

    async def test_bare_records_of_one_product_have_one_deterministic_target(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        """Identical rescans keep landing on one record, whatever the page does.

        The order the branch first shipped said nothing inside the group of
        bare records a scan creates: three identical scans of one code were
        measured landing on Beta, then Alfa, then Beta. Every bump is an
        UPDATE, which moves the row's physical position, so a target chosen
        by page order drifts from one scan to the next. The test measures
        that directly — N identical scans, one id — instead of arranging
        ages against the page, which depends on where Postgres happens to
        put the new tuple version and passed about half the time without the
        ``created_at`` key.
        """
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _location(db, org_id, async_test_user.id, 'Bare Shelf')
        await db.commit()
        code = _barcode()

        scanned = await assign_label_or_barcode(
            db,
            code,
            LabelAssignRequest(location_id=shelf.id, name='Mąka', quantity=1),
            async_test_user,
        )
        await db.commit()

        bare = [scanned]
        for _ in range(3):
            sibling = Item(
                organization_id=org_id,
                storage_location_id=shelf.id,
                template_id=scanned.template_id,
                name='Mąka',
                quantity=Decimal('1'),
            )
            db.add(sibling)
            await db.commit()
            bare.append(sibling)

        # Distinct ages in an order unrelated to insertion: the target is the
        # oldest record, not the first one on the page.
        now = datetime.now(UTC)
        for record, days in zip(bare, (2, 0, 3, 1), strict=True):
            record.created_at = now - timedelta(days=days)
        await db.commit()
        oldest = bare[2]

        landed: list[uuid.UUID] = []
        for _ in range(4):
            again = await assign_label_or_barcode(
                db,
                code,
                LabelAssignRequest(location_id=shelf.id, name='Mąka', quantity=1),
                async_test_user,
            )
            await db.commit()
            landed.append(again.id)

        assert landed == [oldest.id] * 4, 'one target, however the rows lie'
        await db.refresh(oldest)
        assert oldest.quantity == Decimal('5')


async def _close_current_period(db: AsyncSession, user) -> None:
    today = date.today()
    await close_period(db, user.organization_id, today.year, today.month, user.id)
    # The request that closes a period commits it; the HTTP request below is
    # another session and only sees what was kept.
    await db.commit()


@pytest.mark.asyncio
class TestTheRescanRespectsTheClosedPeriod:
    """A rescan bumps existing stock, so it falls under the period lock."""

    async def test_a_rescan_in_a_closed_period_is_refused_and_writes_nothing(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        shelf = await _location(db, org_id, async_test_user.id, 'Closed Shelf')
        await db.commit()
        code = _barcode()
        request = LabelAssignRequest(location_id=shelf.id, name='Herbata', quantity=1)

        first = await assign_label_or_barcode(db, code, request, async_test_user)
        await db.commit()
        await _close_current_period(db, async_test_user)

        with pytest.raises(PeriodClosedError):
            await assign_label_or_barcode(db, code, request, async_test_user)
        await db.rollback()

        await db.refresh(first)
        assert first.quantity == Decimal('1'), 'no quantity lands in a closed period'

    async def test_the_refusal_over_http_is_a_named_conflict(
        self, real_async_db_session: AsyncSession, real_async_client, async_test_user
    ) -> None:
        db = real_async_db_session
        shelf = await _location(
            db, async_test_user.organization_id, async_test_user.id, 'Closed Http'
        )
        await db.commit()
        code = _barcode()
        headers = {
            'Authorization': (
                f'Bearer {create_access_token(data={"sub": str(async_test_user.id)})}'
            )
        }
        body = {
            'name': 'Herbata',
            'location_id': str(shelf.id),
            'quantity': 1,
        }
        url = f'/api/v1/labels/scan/{code}/assign'

        created = await real_async_client.post(url, headers=headers, json=body)
        assert created.status_code == status.HTTP_200_OK, created.text
        await _close_current_period(db, async_test_user)

        refused = await real_async_client.post(url, headers=headers, json=body)

        assert refused.status_code == status.HTTP_409_CONFLICT, refused.text
        assert 'PERIOD_CLOSED' in refused.text
        # The scan dialog has no date to change: the stock lands today, so the
        # only way past the refusal is the period being reopened.
        message = refused.json()['detail']['message']
        assert 'document date' not in message, message
        assert 'reopen' in message, message
