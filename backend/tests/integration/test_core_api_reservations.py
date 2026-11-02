"""Tests for list_reservations_async (app.services._stock_reservation).

Each per-document reservation creates a ``StockReservation`` row
linking a document to the grain it holds: the group's anchor, the batch,
the owner. ``list_reservations_async`` is the read surface that surfaces
these records to admin/UI tools.

Contract:
    - Filter by organization (always), optional document_id,
      product_template_id, location_id — the last two read through the
      row's anchor.
    - Returns StockReservation rows; the product and the shelf are the
      anchor's (``r.anchor_id``).
    - Org-scoped: reservations from another org never returned.

The ``active_only`` filter, which dropped rows whose grain said nothing was
held, went with the grain table: a row is the hold.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ShelfRow
from app.models.product_template import ProductTemplate
from app.models.stock_anchor import StockAnchor
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation
from app.services._stock_reservation import list_reservations_async

from ._holds import hold_async
from ._shelf import put_on_shelf, shelf_keeper

pytestmark = pytest.mark.integration


async def _make_template(
    db: AsyncSession, org_id, *, name: str = 'Test'
) -> ProductTemplate:
    tpl = ProductTemplate(organization_id=org_id, name=name)
    db.add(tpl)
    await db.flush()
    await db.refresh(tpl)
    return tpl


async def _stock(
    db,
    org_id,
    template: ProductTemplate,
    location_id,
    quantity: Decimal,
) -> ShelfRow:
    """*quantity* on the shelf, put there through a record, and the group it stands in.

    The reservation rows below hold stock the records carry, as every row a
    door writes does — the database refuses one that outgrows its grain.
    """
    keeper = await shelf_keeper(db, org_id)
    await put_on_shelf(db, keeper, template, location_id, quantity)
    return (
        await db.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == org_id,
                ShelfRow.product_template_id == template.id,
                ShelfRow.storage_location_id == location_id,
            )
        )
    ).one()


async def _make_reservation(
    db, document_id, grain: ShelfRow, quantity: Decimal
) -> StockReservation:
    # The row names the grain it holds, as the reservation writes it: the
    # group's anchor, the batch, the owner.
    res = await hold_async(db, grain, quantity, document_id=document_id)
    await db.flush()
    await db.refresh(res)
    return res


@pytest.mark.asyncio
class TestCoreStockListReservationsAPI:
    """list_reservations_async (service-level)."""

    async def test_empty_when_no_reservations(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location: StorageLocation,
    ):
        """Org with no reservations → empty list (never None)."""
        db = real_async_db_session
        result = await list_reservations_async(
            db, async_test_storage_location.organization_id
        )
        assert result == []

    async def test_returns_existing_reservations(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location: StorageLocation,
    ):
        """Create 2 reservations → list returns both as DTOs."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl = await _make_template(db, org_id)
        grain = await _stock(
            db,
            org_id,
            tpl,
            async_test_storage_location.id,
            Decimal('100'),
        )

        await _make_reservation(db, uuid4(), grain, Decimal('5'))
        await _make_reservation(db, uuid4(), grain, Decimal('3'))
        await db.commit()

        result = await list_reservations_async(db, org_id)

        assert len(result) == 2
        assert all(isinstance(r, StockReservation) for r in result)
        assert sum(r.quantity for r in result) == Decimal('8')

    async def test_filter_by_document_id(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location: StorageLocation,
    ):
        """document_id filter narrows results to one document's reservations."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl = await _make_template(db, org_id)
        grain = await _stock(
            db,
            org_id,
            tpl,
            async_test_storage_location.id,
            Decimal('100'),
        )

        doc_a, doc_b = uuid4(), uuid4()
        await _make_reservation(db, doc_a, grain, Decimal('2'))
        await _make_reservation(db, doc_a, grain, Decimal('3'))
        await _make_reservation(db, doc_b, grain, Decimal('4'))
        await db.commit()

        result = await list_reservations_async(db, org_id, document_id=doc_a)
        assert len(result) == 2
        assert all(r.document_id == doc_a for r in result)
        assert sum(r.quantity for r in result) == Decimal('5')

    async def test_filter_by_product_template_id(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location: StorageLocation,
    ):
        """product_template_id filter narrows through the row's anchor."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl_a = await _make_template(db, org_id, name='A')
        tpl_b = await _make_template(db, org_id, name='B')
        grain_a = await _stock(
            db,
            org_id,
            tpl_a,
            async_test_storage_location.id,
            Decimal('10'),
        )
        grain_b = await _stock(
            db,
            org_id,
            tpl_b,
            async_test_storage_location.id,
            Decimal('10'),
        )

        await _make_reservation(db, uuid4(), grain_a, Decimal('1'))
        await _make_reservation(db, uuid4(), grain_b, Decimal('1'))
        await db.commit()

        result = await list_reservations_async(db, org_id, product_template_id=tpl_a.id)
        assert len(result) == 1
        anchor = await db.get(StockAnchor, result[0].anchor_id)
        assert anchor.product_template_id == tpl_a.id

    async def test_does_not_leak_other_orgs(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location: StorageLocation,
    ):
        """Reservations from another org are never returned."""
        from ._core_api_helpers import make_other_org

        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        other_org = await db.run_sync(make_other_org)

        tpl = await _make_template(db, org_id)
        grain = await _stock(
            db,
            org_id,
            tpl,
            async_test_storage_location.id,
            Decimal('10'),
        )

        # The other organization's hold, on stock of its own.
        other_tpl = await _make_template(db, other_org.id)
        other_keeper = await shelf_keeper(db, other_org.id)
        other_shelf = StorageLocation(
            organization_id=other_org.id, created_by=other_keeper.id, name='Shelf'
        )
        db.add(other_shelf)
        await db.flush()
        other_grain = await _stock(
            db,
            other_org.id,
            other_tpl,
            other_shelf.id,
            Decimal('10'),
        )

        await _make_reservation(db, uuid4(), grain, Decimal('1'))
        await _make_reservation(db, uuid4(), other_grain, Decimal('1'))
        await db.commit()

        result = await list_reservations_async(db, org_id)
        assert len(result) == 1

    async def test_limit_caps_result_size(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location: StorageLocation,
    ):
        """limit caps result size."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl = await _make_template(db, org_id)
        grain = await _stock(
            db,
            org_id,
            tpl,
            async_test_storage_location.id,
            Decimal('100'),
        )

        for _ in range(5):
            await _make_reservation(db, uuid4(), grain, Decimal('1'))
        await db.commit()

        result = await list_reservations_async(db, org_id, limit=2)
        assert len(result) == 2

    async def test_row_carries_its_grain_and_doc_metadata(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location: StorageLocation,
    ):
        """The row names its document, and its anchor names the product and shelf."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl = await _make_template(db, org_id, name='Widget')
        grain = await _stock(
            db,
            org_id,
            tpl,
            async_test_storage_location.id,
            Decimal('10'),
        )
        doc_id = uuid4()

        await _make_reservation(db, doc_id, grain, Decimal('2'))
        await db.commit()

        result = await list_reservations_async(db, org_id)
        assert len(result) == 1
        r = result[0]
        assert r.document_id == doc_id
        assert r.document_line_id is None
        anchor = await db.get(StockAnchor, r.anchor_id)
        assert anchor.product_template_id == tpl.id
        assert anchor.storage_location_id == async_test_storage_location.id
        assert (r.lot_id, r.owner_id) == (None, None)
        assert r.quantity == Decimal('2')
