"""A record that changes shelves takes its stock with it, whichever door it used.

A record's shelf is written by several doors, and only ``move_item`` and the
bulk edit carried the quant across. ``PUT /items/{id}`` — and everything built
on the same ``update_item``: ``core_api.items.update_async`` and a re-imported sheet
naming another shelf — set the column and left the quant where it stood: the
record said "shelf B", the register said "shelf A", and the reconciliation
counted the difference twice.

The quant table is gone and the records are the stock, so the shelf follows
the record by itself; what must follow it too is the movement ledger, the
second number the reconciliation holds the shelf to. Every door here is
measured on both: what the records' view holds on each shelf, and that the
ledger nets to the same.

The bulk edit carried it only when the quantity stayed put. With a quantity in
the same request the relocation sat in the ``elif`` of the quantity change, so
the difference landed on the new shelf and the old one never went down.

The doors, from
``git grep -nE "update_item\\(|bulk_update_items\\(|move_item\\(" backend/app``
and ``git grep -nE "\\.storage_location_id\\s*=[^=]|setattr\\(item," backend/app``:

- ``PUT /api/v1/items/{id}`` → ``update_item``
- ``core_api.items.update_async`` → ``update_item``
- the sheet import updating a product it matched → ``update_item`` (location
  only: an overwrite leaves the quantity to the ledger)
- ``PATCH /api/v1/items/bulk`` → ``bulk_update_items``
- ``PATCH /api/v1/items/{id}/move`` → ``move_item`` (location only)
- the equipment bulk move → ``core_api.items.update_async`` (location only)

The consume path parks an emptied record on a virtual shelf; it holds nothing
by then, so there is nothing to carry.
"""

import uuid
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.contracts import ItemUpdateDTO, UserContextDTO
from app.core.public_api import core_api
from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.services.items._import import import_items
from tests.integration._shelf import post_on_shelf, put_on_shelf, shelf_keeper

pytestmark = pytest.mark.integration


# ── the sync (HTTP) doors ────────────────────────────────────────────────────


def _shelf_and_ledger(template_id, location_id) -> tuple:
    """What the records' view holds on the shelf, and what the ledger nets to there."""
    shelf = select(func.coalesce(func.sum(ShelfRow.quantity), 0)).where(
        ShelfRow.product_template_id == template_id,
        ShelfRow.storage_location_id == location_id,
    )

    def moved(column):
        return select(func.coalesce(func.sum(StockMove.quantity), 0)).where(
            StockMove.product_template_id == template_id,
            StockMove.state == 'done',
            column == location_id,
        )

    return shelf, moved(StockMove.to_location_id), moved(StockMove.from_location_id)


def _agreed(shelf: Decimal, arrived: Decimal, left: Decimal) -> Decimal:
    assert shelf == arrived - left, (
        f'the shelf holds {shelf} and the ledger nets to {arrived - left}: '
        'the record changed shelves without its movement'
    )
    return Decimal(shelf)


def _on_hand(db: Session, template_id, location_id) -> Decimal:
    return _agreed(*(db.scalar(q) for q in _shelf_and_ledger(template_id, location_id)))


@pytest.fixture
def stocked(client, auth_headers, db_session: Session, test_storage_location):
    """Five on shelf A, in the record and in the ledger; shelf B empty."""
    org_id = test_storage_location.organization_id
    template = ProductTemplate(
        organization_id=org_id, name='Pork Loin', sku=f'PL-{uuid.uuid4().hex[:8]}'
    )
    db_session.add(template)
    db_session.flush()
    shelf_b = StorageLocation(
        organization_id=org_id,
        name='Garage Freezer',
        created_by=test_storage_location.created_by,
    )
    db_session.add(shelf_b)
    db_session.commit()
    record = post_on_shelf(client, auth_headers, template, test_storage_location.id, 5)
    db_session.expire_all()
    item = db_session.get(Item, uuid.UUID(record['id']))
    return item, template, test_storage_location, shelf_b


def test_put_carries_the_stock_to_the_new_shelf(
    client, auth_headers, db_session, stocked
) -> None:
    item, template, shelf_a, shelf_b = stocked

    response = client.put(
        f'/api/v1/items/{item.id}',
        json={'location_id': str(shelf_b.id)},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert _on_hand(db_session, template.id, shelf_a.id) == Decimal('0')
    assert _on_hand(db_session, template.id, shelf_b.id) == Decimal('5')


def test_put_with_a_quantity_carries_the_stock_and_the_change(
    client, auth_headers, db_session, stocked
) -> None:
    item, template, shelf_a, shelf_b = stocked

    response = client.put(
        f'/api/v1/items/{item.id}',
        json={'location_id': str(shelf_b.id), 'quantity': 7},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert _on_hand(db_session, template.id, shelf_a.id) == Decimal('0')
    assert _on_hand(db_session, template.id, shelf_b.id) == Decimal('7')


def test_bulk_carries_the_stock_to_the_new_shelf(
    client, auth_headers, db_session, stocked
) -> None:
    item, template, shelf_a, shelf_b = stocked

    response = client.patch(
        '/api/v1/items/bulk',
        json={
            'item_ids': [str(item.id)],
            'update_data': {'location_id': str(shelf_b.id)},
        },
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert _on_hand(db_session, template.id, shelf_a.id) == Decimal('0')
    assert _on_hand(db_session, template.id, shelf_b.id) == Decimal('5')


def test_bulk_with_a_quantity_carries_the_stock_and_the_change(
    client, auth_headers, db_session, stocked
) -> None:
    item, template, shelf_a, shelf_b = stocked

    response = client.patch(
        '/api/v1/items/bulk',
        json={
            'item_ids': [str(item.id)],
            'update_data': {'location_id': str(shelf_b.id), 'quantity': 3},
        },
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert _on_hand(db_session, template.id, shelf_a.id) == Decimal('0')
    assert _on_hand(db_session, template.id, shelf_b.id) == Decimal('3')


def test_move_carries_the_stock_to_the_new_shelf(
    client, auth_headers, db_session, stocked
) -> None:
    item, template, shelf_a, shelf_b = stocked

    response = client.patch(
        f'/api/v1/items/{item.id}/move',
        json={'to_location_id': str(shelf_b.id)},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert _on_hand(db_session, template.id, shelf_a.id) == Decimal('0')
    assert _on_hand(db_session, template.id, shelf_b.id) == Decimal('5')


# ── the async doors: core_api and the sheet import ───────────────────────────


async def _on_hand_async(db: AsyncSession, template_id, location_id) -> Decimal:
    return _agreed(
        *[await db.scalar(q) for q in _shelf_and_ledger(template_id, location_id)]
    )


async def _stocked_async(db: AsyncSession, org_id, shelf_a: StorageLocation):
    template = ProductTemplate(
        organization_id=org_id, name='Cocoa', sku=f'CO-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    await db.flush()
    shelf_b = StorageLocation(
        organization_id=org_id, name='Pantry Top', created_by=shelf_a.created_by
    )
    db.add(shelf_b)
    await db.flush()
    item = await put_on_shelf(
        db, await shelf_keeper(db, org_id), template, shelf_a.id, 5
    )
    item.label_code = 'INV-0042'
    await db.commit()
    return item, template, shelf_b


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


@pytest.mark.asyncio
async def test_core_api_update_carries_the_stock_to_the_new_shelf(
    real_async_db_session, async_test_user, async_test_storage_location
) -> None:
    db = real_async_db_session
    shelf_a = async_test_storage_location
    item, template, shelf_b = await _stocked_async(
        db, async_test_user.organization_id, shelf_a
    )

    await core_api.items.update_async(
        db,
        async_test_user.organization_id,
        item.id,
        ItemUpdateDTO(location_id=shelf_b.id),
        _ctx(async_test_user),
    )

    assert await _on_hand_async(db, template.id, shelf_a.id) == Decimal('0')
    assert await _on_hand_async(db, template.id, shelf_b.id) == Decimal('5')


@pytest.mark.asyncio
async def test_core_api_update_with_a_quantity_carries_the_stock_and_the_change(
    real_async_db_session, async_test_user, async_test_storage_location
) -> None:
    db = real_async_db_session
    shelf_a = async_test_storage_location
    item, template, shelf_b = await _stocked_async(
        db, async_test_user.organization_id, shelf_a
    )

    await core_api.items.update_async(
        db,
        async_test_user.organization_id,
        item.id,
        ItemUpdateDTO(location_id=shelf_b.id, quantity=Decimal('2')),
        _ctx(async_test_user),
    )

    assert await _on_hand_async(db, template.id, shelf_a.id) == Decimal('0')
    assert await _on_hand_async(db, template.id, shelf_b.id) == Decimal('2')


@pytest.mark.asyncio
async def test_a_reimported_sheet_naming_another_shelf_carries_the_stock(
    real_async_db_session, async_test_user, async_test_storage_location
) -> None:
    db = real_async_db_session
    shelf_a = async_test_storage_location
    _item, template, shelf_b = await _stocked_async(
        db, async_test_user.organization_id, shelf_a
    )

    result = await import_items(
        db,
        pd.DataFrame(
            [{'Name': 'Cocoa', 'Storage': shelf_b.name, 'Label Code': 'INV-0042'}]
        )
        .to_csv(index=False)
        .encode(),
        'stock.csv',
        {'name': 'Name', 'location': 'Storage', 'label_code': 'Label Code'},
        _ctx(async_test_user),
        create_missing_locations=False,
        create_missing_categories=False,
        on_label_match='overwrite',
    )

    assert result['updated'] == 1, result
    assert await _on_hand_async(db, template.id, shelf_a.id) == Decimal('0')
    assert await _on_hand_async(db, template.id, shelf_b.id) == Decimal('5')
