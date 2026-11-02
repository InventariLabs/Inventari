"""A change to a record's quantity lands on the record's own batch and owner.

A record names the batch and the owner its stock is in (``Item.lot_id``,
``Item.owner_id``), but the bridge that carried a quantity change to the
quants did not look: out of the shelf it took by removal strategy, into it it
put onto the batch-less quant. Taking two off the record of the later batch
took them off the earlier one; adding three put them on no batch at all; a
move carried the earlier batch across and left the record's own behind. The
shelf still agreed in total, and disagreed batch by batch with every edit.

The quants are gone and the shelf is what its records hold, batch by batch
(``stock_quants_from_records``). Every door that changes a record's quantity
or shelf is exercised here on the same shelf: two batches, one record of
each, the record of the later batch changed — and the shelf read per batch
afterwards. Consuming a batch that is held or recalled is refused, as it is
everywhere else; throwing it away is not.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.contracts._stock_dtos import LotStatus
from app.core.testing import ShelfRow, seed_org_storage_types
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


class _Shelf:
    """Aisle 1 with batch B-01 (early) and B-02 (late), one record of each, five apiece."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.org = Organization(name='Two Batch Warehouse')
        db.add(self.org)
        db.flush()
        seed_org_storage_types(db, self.org.id)
        user = User(
            email=f'batch-{uuid.uuid4().hex[:6]}@test.com',
            hashed_password=get_password_hash('pass'),
            full_name='Batch User',
            organization_id=self.org.id,
            role='admin',
            is_active=True,
        )
        db.add(user)
        db.flush()
        self.headers = {
            'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
        }
        self.aisle, self.dock = (
            StorageLocation(organization_id=self.org.id, created_by=user.id, name=name)
            for name in ('Aisle 1', 'Dock')
        )
        self.product = ProductTemplate(
            organization_id=self.org.id, name='Rice', sku=f'RI-{uuid.uuid4().hex[:8]}'
        )
        db.add_all([self.aisle, self.dock, self.product])
        db.flush()
        self.early, self.late = (
            StockLot(
                organization_id=self.org.id,
                product_template_id=self.product.id,
                name=name,
                expiry_date=expiry,
            )
            for name, expiry in (('B-01', date(2031, 3, 1)), ('B-02', date(2031, 9, 1)))
        )
        db.add_all([self.early, self.late])
        db.flush()
        self.first = self.record(self.aisle, '5', lot=self.early)
        self.second = self.record(self.aisle, '5', lot=self.late)
        db.commit()

    def record(self, shelf, qty: str, lot=None, owner=None) -> Item:
        item = Item(
            organization_id=self.org.id,
            storage_location_id=shelf.id,
            template_id=self.product.id,
            name='Rice',
            quantity=Decimal(qty),
            lot_id=lot.id if lot else None,
            owner_id=owner.id if owner else None,
        )
        self.db.add(item)
        anchor_pending_records(self.db)
        self.db.flush()
        return item

    def on(self, shelf) -> dict:
        """What the shelf holds, per (batch, owner), empty groups left out."""
        self.db.expire_all()
        return {
            (row.lot_id, row.owner_id): row.quantity
            for row in self.db.scalars(
                select(ShelfRow).where(
                    ShelfRow.organization_id == self.org.id,
                    ShelfRow.storage_location_id == shelf.id,
                )
            )
            if row.quantity
        }


@pytest.fixture
def shelf(db_session: Session) -> _Shelf:
    return _Shelf(db_session)


def _url(s: _Shelf, action: str = '') -> str:
    return f'/api/v1/items/{s.second.id}{action}'


# Each door, applied to the record of the later batch: (method, path, body,
# what the later batch holds on the aisle afterwards).
_DOORS = {
    'quantity down': ('patch', '/quantity', {'quantity': 3}, Decimal('3')),
    'quantity up': ('patch', '/quantity', {'quantity': 8}, Decimal('8')),
    'consume': ('patch', '/consume', {'quantity': 2}, Decimal('3')),
    'discard': (
        'patch',
        '/discard',
        {'quantity': 2, 'reason': 'damaged'},
        Decimal('3'),
    ),
    'edit down': ('put', '', {'quantity': 1}, Decimal('1')),
    'edit up': ('put', '', {'quantity': 9}, Decimal('9')),
    'delete': ('delete', '', None, Decimal('0')),
}


@pytest.mark.parametrize('door', list(_DOORS))
def test_a_door_that_changes_the_quantity_changes_the_records_own_batch(
    client, shelf: _Shelf, door: str
) -> None:
    method, action, body, late_after = _DOORS[door]
    kwargs = {'headers': shelf.headers} | ({'json': body} if body else {})

    response = getattr(client, method)(_url(shelf, action), **kwargs)

    assert response.status_code in (200, 204), response.text
    expected = {(shelf.early.id, None): Decimal('5')}
    if late_after:
        expected[(shelf.late.id, None)] = late_after
    assert shelf.on(shelf.aisle) == expected


def test_a_bulk_edit_changes_the_records_own_batch(client, shelf: _Shelf) -> None:
    response = client.patch(
        '/api/v1/items/bulk',
        headers=shelf.headers,
        json={'item_ids': [str(shelf.second.id)], 'update_data': {'quantity': 2}},
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    assert shelf.on(shelf.aisle) == {
        (shelf.early.id, None): Decimal('5'),
        (shelf.late.id, None): Decimal('2'),
    }


def test_a_restored_record_brings_its_stock_back_to_its_own_batch(
    client, shelf: _Shelf
) -> None:
    assert client.delete(_url(shelf), headers=shelf.headers).status_code == 204

    response = client.post(_url(shelf, '/restore'), headers=shelf.headers)

    assert response.status_code == status.HTTP_200_OK, response.text
    assert shelf.on(shelf.aisle) == {
        (shelf.early.id, None): Decimal('5'),
        (shelf.late.id, None): Decimal('5'),
    }


@pytest.mark.parametrize(
    'door',
    [
        ('patch', '/move', lambda s: {'to_location_id': str(s.dock.id)}),
        ('put', '', lambda s: {'location_id': str(s.dock.id)}),
    ],
    ids=['move', 'edit the shelf'],
)
def test_a_record_that_changes_shelves_takes_its_own_batch_along(
    client, shelf: _Shelf, door
) -> None:
    method, action, body = door

    response = getattr(client, method)(
        _url(shelf, action), headers=shelf.headers, json=body(shelf)
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    assert shelf.on(shelf.aisle) == {(shelf.early.id, None): Decimal('5')}
    assert shelf.on(shelf.dock) == {(shelf.late.id, None): Decimal('5')}


@pytest.mark.parametrize('status_', [LotStatus.RECALLED, LotStatus.QUARANTINED])
def test_a_held_batch_is_not_consumed_but_can_be_thrown_away(
    client, shelf: _Shelf, status_: str
) -> None:
    shelf.late.status = status_
    shelf.db.commit()

    consumed = client.patch(
        _url(shelf, '/consume'), headers=shelf.headers, json={'quantity': 2}
    )
    assert consumed.status_code == status.HTTP_400_BAD_REQUEST, consumed.text
    assert shelf.on(shelf.aisle) == {
        (shelf.early.id, None): Decimal('5'),
        (shelf.late.id, None): Decimal('5'),
    }

    discarded = client.patch(
        _url(shelf, '/discard'),
        headers=shelf.headers,
        json={'quantity': 2, 'reason': 'recalled'},
    )
    assert discarded.status_code == status.HTTP_200_OK, discarded.text
    assert shelf.on(shelf.aisle) == {
        (shelf.early.id, None): Decimal('5'),
        (shelf.late.id, None): Decimal('3'),
    }


def test_a_consigned_record_changes_the_consignors_stock(client, shelf: _Shelf) -> None:
    consignor = Partner(organization_id=shelf.org.id, name='Consignor', type='SUPPLIER')
    shelf.db.add(consignor)
    shelf.db.flush()
    consigned = shelf.record(shelf.dock, '4', owner=consignor)
    shelf.record(shelf.dock, '4')
    shelf.db.commit()

    response = client.patch(
        f'/api/v1/items/{consigned.id}/quantity',
        headers=shelf.headers,
        json={'quantity': 1},
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    assert shelf.on(shelf.dock) == {
        (None, consignor.id): Decimal('1'),
        (None, None): Decimal('4'),
    }


def test_a_record_with_no_batch_comes_off_the_batchless_stock_first(
    client, shelf: _Shelf
) -> None:
    loose = shelf.record(shelf.aisle, '4')
    shelf.db.commit()

    response = client.patch(
        f'/api/v1/items/{loose.id}/quantity',
        headers=shelf.headers,
        json={'quantity': 1},
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    assert shelf.on(shelf.aisle) == {
        (shelf.early.id, None): Decimal('5'),
        (shelf.late.id, None): Decimal('5'),
        (None, None): Decimal('1'),
    }
