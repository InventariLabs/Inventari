"""Carrying goods from one of your own places to another is a movement.

The moves register (`/inventory/moves`) says what it is for in its own
subtitle: "What came in, what left, and what moved between your own places".
It has a "Moved" filter, and `StockMove` has both `from_location_id` and
`to_location_id`. Relocating a record wrote neither: `relocate_stock_async`
consumed the source quants and re-created them at the destination without
recording a single move, so the filter could not match anything and the
product card's Movements tab said "This product has not moved here" about a
shelf the goods were standing on.

Three screens said three different things about the same event a minute old —
the change history was the only one that knew.

One function serves both the single move and the bulk edit, which is where
the movement is recorded: the two paths cannot drift apart again.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.schemas.item import ItemMove
from app.services.items import move_item
from tests.integration._core_api_helpers import make_user_context
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _template(db: AsyncSession, org_id) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org_id,
        name='Bananas',
        sku=f'BAN-{uuid.uuid4().hex[:8]}',
    )
    db.add(template)
    await db.flush()
    return template


async def _other_shelf(db: AsyncSession, org_id, owner_id) -> StorageLocation:
    shelf = StorageLocation(
        organization_id=org_id,
        name='QAF16 Partition 1',
        created_by=owner_id,
    )
    db.add(shelf)
    await db.flush()
    return shelf


async def _carry(db: AsyncSession, record: Item, shelf: StorageLocation, user) -> None:
    """Move *record* to *shelf* the way ``PATCH /items/{id}/move`` does."""
    await move_item(
        db,
        record,
        ItemMove(to_location_id=shelf.id),
        user=make_user_context(record.organization_id, user.id),
    )


async def _moves_between(db: AsyncSession, template_id) -> list[StockMove]:
    """The product's moves from one of the organization's places to another."""
    result = await db.execute(
        select(StockMove).where(
            StockMove.product_template_id == template_id,
            StockMove.from_location_id.is_not(None),
            StockMove.to_location_id.is_not(None),
        )
    )
    return list(result.scalars().all())


async def test_the_relocation_writes_a_move_with_both_ends(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    async_test_user,
) -> None:
    db = real_async_db_session
    template = await _template(db, async_test_household.id)
    destination = await _other_shelf(
        db, async_test_household.id, async_test_storage_location.created_by
    )
    record = await put_on_shelf(
        db, async_test_user, template, async_test_storage_location.id, 2
    )

    await _carry(db, record, destination, async_test_user)

    moves = await _moves_between(db, template.id)
    assert len(moves) == 1
    assert moves[0].from_location_id == async_test_storage_location.id
    assert moves[0].to_location_id == destination.id
    assert moves[0].quantity == Decimal('2')


async def test_the_move_carries_the_batch_the_goods_carried(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    async_test_user,
) -> None:
    db = real_async_db_session
    template = await _template(db, async_test_household.id)
    destination = await _other_shelf(
        db, async_test_household.id, async_test_storage_location.created_by
    )
    lot = StockLot(
        organization_id=async_test_household.id,
        product_template_id=template.id,
        name=f'LOT-{uuid.uuid4().hex[:6]}',
    )
    db.add(lot)
    await db.flush()
    record = await put_on_shelf(
        db, async_test_user, template, async_test_storage_location.id, 4, lot_id=lot.id
    )

    await _carry(db, record, destination, async_test_user)

    moves = await _moves_between(db, template.id)
    assert len(moves) == 1
    assert moves[0].lot_id == lot.id


def test_the_moved_filter_and_the_location_tab_both_find_it(
    client,
    auth_headers: dict[str, str],
    db_session,
    test_storage_location,
) -> None:
    """The two screens that said nothing had happened.

    `/inventory/moves` with the "Moved" filter is `direction=internal`, and the
    product card's Movements tab asks the same endpoint with the location. Both
    read the register, so both were empty for a relocation. Driven through the
    endpoint a person uses, so the whole path is what is asserted.
    """
    org_id = test_storage_location.organization_id
    destination = StorageLocation(
        organization_id=org_id,
        name='QAF16 Partition 1',
        created_by=test_storage_location.created_by,
    )
    db_session.add(destination)
    db_session.commit()
    created = client.post(
        '/api/v1/items',
        json={
            'name': f'Bananas {uuid.uuid4().hex[:6]}',
            'quantity': '2',
            'location_id': str(test_storage_location.id),
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    item_id = created.json()['id']
    template_id = created.json()['template_id']

    moved = client.patch(
        f'/api/v1/items/{item_id}/move',
        json={'to_location_id': str(destination.id)},
        headers=auth_headers,
    )
    assert moved.status_code == 200, moved.text

    register = client.get(
        '/api/v1/stock-moves', params={'direction': 'internal'}, headers=auth_headers
    )
    assert register.status_code == 200
    rows = register.json()['items']
    assert any(row['product_template_id'] == template_id for row in rows), (
        'the "Moved" filter still matches nothing'
    )

    at_destination = client.get(
        '/api/v1/stock-moves',
        params={
            'product_template_id': template_id,
            'location_id': str(destination.id),
        },
        headers=auth_headers,
    )
    assert at_destination.status_code == 200
    assert at_destination.json()['items'], (
        'the destination tab still says the product has not moved here'
    )


async def test_the_move_names_the_record_and_who_carried_it(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    async_test_user,
) -> None:
    """A row in the register that leads nowhere explains nothing."""
    db = real_async_db_session
    template = await _template(db, async_test_household.id)
    destination = await _other_shelf(
        db, async_test_household.id, async_test_storage_location.created_by
    )
    record = await put_on_shelf(
        db, async_test_user, template, async_test_storage_location.id, 1
    )

    await _carry(db, record, destination, async_test_user)

    moves = await _moves_between(db, template.id)
    assert len(moves) == 1
    assert moves[0].reference_type == 'item'
    assert moves[0].reference_id == record.id
    assert moves[0].created_by == async_test_user.id
