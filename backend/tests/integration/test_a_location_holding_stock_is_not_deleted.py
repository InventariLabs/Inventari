"""A location the register says holds stock is not deleted out from under it.

Both guards on deleting a location counted the records standing there and the
movements naming it, and neither looked at the quants — while the quant's
foreign key to its location was ``ON DELETE CASCADE``. Stock the register
would lose with no movement to say so was left to a third guard, the one
reading ``locations_holding_stock_async``.

That guard reads the records and the reservation rows
(``stock_quants_from_records``); the quant table is gone, and the records
are the source of truth. Two things follow, and both are pinned here:

- a location with a record standing on it is refused one guard earlier, by
  the record count — the same guarantee, another door;
- a location documents still promise stock on, with no record left under the
  promise, is refused by the stock guard, whose numbers now come from the
  records' view. A quant with nothing beside it stopped being refused before
  the table went: with no record and no promise behind it there was nothing
  the register would lose.

The doors, from
``git grep -nE "db\\.delete\\((row|storage)\\)" backend/app/services/storage``:

- ``DELETE /api/v1/locations/{id}`` → ``services/storage/_writes.py`` ``delete_storage``
- ``POST /api/v1/locations/reorg`` with a ``delete`` operation →
  ``services/storage/_reorg.py`` ``_check_delete_guards``
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.testing import ShelfRow
from app.i18n.service import get_error_message
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation

from ._holds import hold, past_the_hold_guard
from ._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _shelf_and_template(
    db_session, test_user
) -> tuple[StorageLocation, ProductTemplate]:
    shelf = StorageLocation(
        organization_id=test_user.organization_id,
        created_by=test_user.id,
        name='Back room',
        usage='internal',
    )
    template = ProductTemplate(
        organization_id=test_user.organization_id,
        name='Flour',
        sku=f'FL-{uuid.uuid4().hex[:8]}',
    )
    db_session.add_all([shelf, template])
    db_session.flush()
    return shelf, template


@pytest.fixture
def shelf_with_a_record(client, auth_headers, db_session, test_user) -> StorageLocation:
    """A shelf with a record on it, put there the way the application does it."""
    shelf, template = _shelf_and_template(db_session, test_user)
    db_session.commit()
    post_on_shelf(client, auth_headers, template, shelf.id, Decimal('3'))
    db_session.expire_all()
    return shelf


@pytest.fixture
def shelf_with_a_promise(
    client, auth_headers, db_session, test_user
) -> StorageLocation:
    """A shelf documents still promise stock on, with no record under the promise.

    The record goes the way an archive goes (``is_deleted``); the promise the
    document holds on that shelf is not released with it, so the group the
    view sees is a promise and nothing behind it. The database refuses that
    shape at commit now (``holdguard01``), so it is the one an instance older
    than the guard holds, written past it.
    """
    shelf, template = _shelf_and_template(db_session, test_user)
    db_session.commit()
    post_on_shelf(client, auth_headers, template, shelf.id, Decimal('3'))
    db_session.expire_all()
    grain = db_session.scalar(
        select(ShelfRow).where(
            ShelfRow.storage_location_id == shelf.id,
            ShelfRow.product_template_id == template.id,
        )
    )
    record = db_session.scalar(
        select(Item).where(
            Item.storage_location_id == shelf.id,
            Item.template_id == template.id,
            Item.is_deleted.is_(False),
        )
    )
    with past_the_hold_guard(db_session):
        record.is_deleted = True
        hold(db_session, grain, Decimal('2'))
    db_session.commit()
    return shelf


def _still_there(db_session, shelf: StorageLocation) -> bool:
    """The location stands, and the records' view still has its one group."""
    db_session.expire_all()
    groups = db_session.scalars(
        select(ShelfRow).where(ShelfRow.storage_location_id == shelf.id)
    ).all()
    return db_session.get(StorageLocation, shelf.id) is not None and len(groups) == 1


def test_delete_refuses_a_location_with_a_record_on_it(
    client, auth_headers, db_session, shelf_with_a_record
) -> None:
    shelf = shelf_with_a_record

    response = client.delete(f'/api/v1/locations/{shelf.id}', headers=auth_headers)

    assert response.status_code == 400, response.text
    assert response.json()['detail'] == {
        'code': 'STORAGE_DELETE_FAILED_ITEMS',
        'message': get_error_message('storage_delete_failed_items', 'en'),
        'lang': 'en',
    }
    assert _still_there(db_session, shelf)


def test_delete_refuses_a_location_documents_still_promise(
    client, auth_headers, db_session, shelf_with_a_promise
) -> None:
    shelf = shelf_with_a_promise

    response = client.delete(f'/api/v1/locations/{shelf.id}', headers=auth_headers)

    # The register is the third guard: stock the application put there always
    # names the location in a movement, and the movement guard answers first.
    assert response.status_code == 409, response.text
    assert response.json()['detail'] == {
        'code': 'STORAGE_DELETE_BLOCKED_BY_MOVEMENTS',
        'message': get_error_message(
            'storage_delete_blocked_by_movements', 'en', count=1
        ),
    }
    assert _still_there(db_session, shelf)


def test_reorg_refuses_to_delete_a_location_with_a_record_on_it(
    client, auth_headers, db_session, shelf_with_a_record
) -> None:
    shelf = shelf_with_a_record

    response = client.post(
        '/api/v1/locations/reorg',
        headers=auth_headers,
        json={'operations': [{'op': 'delete', 'id': str(shelf.id)}]},
    )

    body = response.json()
    assert body['applied'] is False, body
    # Records, then the movements they posted, then the register itself —
    # the reorg gathers every guard that holds the door.
    assert [r['reason'] for r in body['rejections']] == [
        get_error_message('storage_delete_failed_items', 'en'),
        get_error_message('storage_delete_blocked_by_movements', 'en', count=1),
        get_error_message('storage_delete_blocked_by_stock', 'en'),
    ]
    assert _still_there(db_session, shelf)


def test_reorg_refuses_to_delete_a_location_documents_still_promise(
    client, auth_headers, db_session, shelf_with_a_promise
) -> None:
    shelf = shelf_with_a_promise

    response = client.post(
        '/api/v1/locations/reorg',
        headers=auth_headers,
        json={'operations': [{'op': 'delete', 'id': str(shelf.id)}]},
    )

    body = response.json()
    assert body['applied'] is False, body
    assert [r['reason'] for r in body['rejections']] == [
        get_error_message('storage_delete_blocked_by_movements', 'en', count=1),
        get_error_message('storage_delete_blocked_by_stock', 'en'),
    ]
    assert _still_there(db_session, shelf)
