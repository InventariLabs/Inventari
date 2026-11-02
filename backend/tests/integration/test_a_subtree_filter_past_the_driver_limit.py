"""A warehouse with tens of thousands of places below it still filters.

The movement journal and the document list narrow to a warehouse by naming
it and every location below it. With one bind parameter per id, a warehouse
holding more than 32 767 places made the driver refuse the statement, and
``GET /stock-moves?location_id=`` and ``GET /warehouse/documents?location_id=``
answered 500. Moving such a subtree read its stock the same way. The ids
travel as one array instead.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.storage_location import StorageLocation
from app.modules.warehouse.document_query_service import list_documents
from app.services import stock_moves_service
from app.services.storage._relocation import products_in_async

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: Past the driver's limit on the arguments of one statement.
_MORE_THAN_THE_DRIVER_ALLOWS = 40_000


def _many_ids():
    return [uuid4() for _ in range(_MORE_THAN_THE_DRIVER_ALLOWS)]


@pytest.fixture
async def warehouse(real_async_db_session: AsyncSession, async_test_user):
    db = real_async_db_session
    row = StorageLocation(
        organization_id=async_test_user.organization_id,
        created_by=async_test_user.id,
        name='WH',
    )
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
def a_huge_subtree(monkeypatch):
    """Every place below the warehouse, without inserting forty thousand rows."""

    async def descendants(db, organization_id, location_id):
        return _many_ids()

    monkeypatch.setattr(stock_moves_service, 'descendant_ids_async', descendants)


async def test_the_journal_of_a_warehouse_with_a_huge_subtree(
    real_async_db_session: AsyncSession, async_test_user, warehouse, a_huge_subtree
):
    db = real_async_db_session
    org_id = async_test_user.organization_id

    moves, total = await stock_moves_service.list_for_org_async(
        db, org_id, location_id=warehouse.id
    )
    rows, row_total = await stock_moves_service.list_rows_for_org_async(
        db, org_id, location_id=warehouse.id
    )

    assert (moves, total, rows, row_total) == ([], 0, [], 0)


async def test_the_documents_of_a_warehouse_with_a_huge_subtree(
    real_async_db_session: AsyncSession, async_test_user, warehouse
):
    documents, total = await list_documents(
        real_async_db_session,
        async_test_user.organization_id,
        location_ids=[warehouse.id, *_many_ids()],
    )

    assert (documents, total) == ([], 0)


async def test_the_stock_of_a_huge_subtree_being_moved(
    real_async_db_session: AsyncSession, async_test_user, warehouse
):
    held = await products_in_async(
        real_async_db_session,
        async_test_user.organization_id,
        [warehouse.id, *_many_ids()],
    )

    assert held == 0
