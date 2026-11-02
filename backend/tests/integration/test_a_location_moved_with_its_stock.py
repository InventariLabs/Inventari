"""A location that physically moves takes its stock's history with it.

Moving a location in the tree used to write one journal row and nothing
else. The products inside kept their shelf id, so their history said
nothing had happened, and anything that reads stock per warehouse from the
movements — the stock on a date above all — showed last month's stock
already standing in the building it was carried to this week.

A move is now one of two things, and the person moving says which:

- a correction of the layout (the default, and all a move used to be):
  the journal row and nothing else — the stock was always there;
- a physical move: one relocation document naming the location, the path it
  left and the path it reached, and a movement of every product inside it
  pointing at that document. Quantities do not change — the shelf ids do not
  either, so the movements name the shelf on both ends and the document says
  where the shelf went.

Before the reorg writes anything it can be asked what a move would carry
(``dry_run``), which is what the confirmation shows the person moving.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy import select, update

from app.models.location_relocation import LocationRelocation
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove, StockMoveReferenceType
from app.models.storage_location import StorageLocation

from ._shelf import post_on_shelf

pytestmark = pytest.mark.integration

_A_MONTH_AGO = datetime.now(UTC) - timedelta(days=30)
_A_WEEK_AGO = datetime.now(UTC) - timedelta(days=7)
_TWO_WEEKS_AGO = datetime.now(UTC) - timedelta(days=14)


def _location(db_session, user, name, parent=None) -> StorageLocation:
    location = StorageLocation(
        organization_id=user.organization_id,
        created_by=user.id,
        name=name,
        parent_id=parent.id if parent is not None else None,
        usage='internal',
    )
    db_session.add(location)
    db_session.flush()
    return location


def _template(db_session, user, name) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=user.organization_id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
    )
    db_session.add(template)
    db_session.flush()
    return template


@pytest.fixture
def warehouses(client, auth_headers, db_session, test_user):
    """Main Warehouse › Cold Storage › Shelf A holding flour and sugar;
    an empty Pantry Building beside it. The stock went in a month ago."""
    main = _location(db_session, test_user, 'Main Warehouse')
    cold = _location(db_session, test_user, 'Cold Storage', main)
    shelf = _location(db_session, test_user, 'Shelf A', cold)
    empty = _location(db_session, test_user, 'Empty Bay', main)
    pantry = _location(db_session, test_user, 'Pantry Building')
    flour = _template(db_session, test_user, 'Flour')
    sugar = _template(db_session, test_user, 'Sugar')
    db_session.commit()
    post_on_shelf(client, auth_headers, flour, shelf.id, Decimal('3'))
    post_on_shelf(client, auth_headers, sugar, shelf.id, Decimal('5'))
    db_session.execute(
        update(StockMove)
        .where(StockMove.organization_id == test_user.organization_id)
        .values(completed_at=_A_MONTH_AGO)
    )
    db_session.commit()
    return {
        'main': main,
        'cold': cold,
        'shelf': shelf,
        'empty': empty,
        'pantry': pantry,
        'flour': flour,
        'sugar': sugar,
    }


def _reorg(client, auth_headers, operations, *, dry_run=False):
    return client.post(
        '/api/v1/locations/reorg',
        headers=auth_headers,
        json={'operations': operations, 'dry_run': dry_run},
    )


def _move(location, parent, relocation=None) -> dict:
    op = {'op': 'move', 'id': str(location.id), 'parent_id': str(parent.id)}
    if relocation is not None:
        op['relocation'] = relocation
    return op


def _relocation_moves(db_session) -> list[StockMove]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(StockMove).where(
                StockMove.reference_type == StockMoveReferenceType.LOCATION_RELOCATION
            )
        ).all()
    )


def _stock_as_of(client, auth_headers, as_of: datetime, location) -> dict:
    response = client.get(
        '/api/v1/stock-as-of',
        headers=auth_headers,
        params={'as_of': as_of.isoformat(), 'location_id': str(location.id)},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return {
        row['product_name']: Decimal(row['quantity'])
        for row in response.json()['items']
    }


def test_a_dry_run_states_what_the_move_carries_and_changes_nothing(
    client, auth_headers, db_session, warehouses
):
    response = _reorg(
        client,
        auth_headers,
        [
            _move(warehouses['cold'], warehouses['pantry']),
            _move(warehouses['empty'], warehouses['pantry']),
        ],
        dry_run=True,
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    body = response.json()
    assert body['applied'] is False
    assert body['rejections'] == []
    cold, empty = body['moves']
    assert cold == {
        'index': 0,
        'id': str(warehouses['cold'].id),
        'name': 'Cold Storage',
        'locations_inside': 1,
        'products': 2,
        'from_path': 'Main Warehouse',
        'to_path': 'Pantry Building',
        'warehouse_changes': True,
    }
    assert empty['products'] == 0
    assert empty['locations_inside'] == 0
    db_session.expire_all()
    assert (
        db_session.get(StorageLocation, warehouses['cold'].id).parent_id
        == warehouses['main'].id
    )


def test_a_move_within_one_warehouse_says_the_warehouse_stays(
    client, auth_headers, warehouses
):
    response = _reorg(
        client,
        auth_headers,
        [_move(warehouses['shelf'], warehouses['empty'])],
        dry_run=True,
    )

    (shelf,) = response.json()['moves']
    assert shelf['from_path'] == 'Main Warehouse / Cold Storage'
    assert shelf['to_path'] == 'Main Warehouse / Empty Bay'
    assert shelf['warehouse_changes'] is False


def test_a_layout_correction_records_no_movement(
    client, auth_headers, db_session, warehouses
):
    response = _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'correction')],
    )

    assert response.json()['applied'] is True
    assert _relocation_moves(db_session) == []
    assert db_session.scalars(select(LocationRelocation)).all() == []


def test_a_physical_move_records_one_document_and_a_move_per_product(
    client, auth_headers, db_session, test_user, warehouses
):
    response = _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'physical')],
    )

    assert response.json()['applied'] is True
    (document,) = db_session.scalars(select(LocationRelocation)).all()
    assert document.location_id == warehouses['cold'].id
    assert document.location_name == 'Cold Storage'
    assert document.from_parent_id == warehouses['main'].id
    assert document.to_parent_id == warehouses['pantry'].id
    assert document.from_path == 'Main Warehouse'
    assert document.to_path == 'Pantry Building'
    assert document.created_by == test_user.id
    moves = _relocation_moves(db_session)
    assert {(m.product_template_id, m.quantity) for m in moves} == {
        (warehouses['flour'].id, Decimal('3')),
        (warehouses['sugar'].id, Decimal('5')),
    }
    shelf_id = warehouses['shelf'].id
    assert all(
        m.from_location_id == shelf_id
        and m.to_location_id == shelf_id
        and m.reference_id == document.id
        for m in moves
    )

    # The register and a product's own history read the same rows, with the
    # document's paths beside them.
    listed = client.get(
        '/api/v1/stock-moves',
        headers=auth_headers,
        params={
            'product_template_id': str(warehouses['flour'].id),
            'reference_type': 'location_relocation',
        },
    ).json()['items']
    assert len(listed) == 1
    assert listed[0]['relocated_location_name'] == 'Cold Storage'
    assert listed[0]['relocated_from_path'] == 'Main Warehouse'
    assert listed[0]['relocated_to_path'] == 'Pantry Building'


def test_the_stock_on_a_date_stands_where_the_location_stood_then(
    client, auth_headers, db_session, warehouses
):
    _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'physical')],
    )
    db_session.execute(update(LocationRelocation).values(moved_at=_A_WEEK_AGO))
    db_session.execute(
        update(StockMove)
        .where(StockMove.reference_type == StockMoveReferenceType.LOCATION_RELOCATION)
        .values(completed_at=_A_WEEK_AGO)
    )
    db_session.commit()
    now = datetime.now(UTC)

    before = {'Flour': Decimal('3'), 'Sugar': Decimal('5')}
    assert _stock_as_of(client, auth_headers, _TWO_WEEKS_AGO, warehouses['main']) == (
        before
    )
    assert (
        _stock_as_of(client, auth_headers, _TWO_WEEKS_AGO, warehouses['pantry']) == {}
    )
    assert _stock_as_of(client, auth_headers, now, warehouses['main']) == {}
    assert _stock_as_of(client, auth_headers, now, warehouses['pantry']) == before


def test_a_layout_correction_moves_the_past_with_it(
    client, auth_headers, db_session, warehouses
):
    """A correction says the stock was always where the tree now puts it."""
    _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'correction')],
    )

    assert _stock_as_of(client, auth_headers, _TWO_WEEKS_AGO, warehouses['pantry']) == {
        'Flour': Decimal('3'),
        'Sugar': Decimal('5'),
    }


def test_undoing_a_physical_move_reverses_its_document(
    client, auth_headers, db_session, warehouses
):
    _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'physical')],
    )
    undo = _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['main'], 'physical')],
    )

    assert undo.json()['applied'] is True
    documents = db_session.scalars(
        select(LocationRelocation).order_by(LocationRelocation.moved_at)
    ).all()
    assert [(d.from_path, d.to_path) for d in documents] == [
        ('Main Warehouse', 'Pantry Building'),
        ('Pantry Building', 'Main Warehouse'),
    ]
    assert len(_relocation_moves(db_session)) == 4
    now = datetime.now(UTC)
    assert _stock_as_of(client, auth_headers, now, warehouses['main']) == {
        'Flour': Decimal('3'),
        'Sugar': Decimal('5'),
    }
    assert _stock_as_of(client, auth_headers, now, warehouses['pantry']) == {}


def test_the_single_edit_records_a_physical_move_too(
    client, auth_headers, db_session, warehouses
):
    """A shelf's own edit sheet is the other door that changes a parent."""
    response = client.put(
        f'/api/v1/locations/{warehouses["shelf"].id}',
        headers=auth_headers,
        json={'parent_id': str(warehouses['pantry'].id), 'relocation': 'physical'},
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    (document,) = db_session.scalars(select(LocationRelocation)).all()
    assert (document.from_path, document.to_path) == (
        'Main Warehouse / Cold Storage',
        'Pantry Building',
    )
    assert len(_relocation_moves(db_session)) == 2


def test_the_single_edit_corrects_the_layout_without_a_movement(
    client, auth_headers, db_session, warehouses
):
    response = client.put(
        f'/api/v1/locations/{warehouses["shelf"].id}',
        headers=auth_headers,
        json={'parent_id': str(warehouses['pantry'].id)},
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    assert _relocation_moves(db_session) == []
