"""A location that physically moves takes its stock's history with it.

Moving a location in the tree is recorded in the journal, and a physical move
carries its stock with it: anything that reads stock per warehouse from the
movements — the stock on a date above all — must not show last month's stock
already standing in the building it was carried to this week.

A move is now one of two things, and the person moving says which:

- a correction of the layout (the default):
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
    assert shelf['from_path'] == 'Main Warehouse › Cold Storage'
    assert shelf['to_path'] == 'Main Warehouse › Empty Bay'
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


def _date_the_relocations(db_session, moved_at: datetime) -> None:
    """Every physical move so far, and the movements it wrote, happened at *moved_at*."""
    db_session.execute(update(LocationRelocation).values(moved_at=moved_at))
    db_session.execute(
        update(StockMove)
        .where(StockMove.reference_type == StockMoveReferenceType.LOCATION_RELOCATION)
        .values(completed_at=moved_at)
    )
    db_session.commit()


def _ledger(client, auth_headers, product) -> list[dict]:
    """The product's movements, newest first, without those a move wrote."""
    response = client.get(
        '/api/v1/stock-moves',
        headers=auth_headers,
        params={'product_template_id': str(product.id)},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return [
        row
        for row in response.json()['items']
        if row['reference_type'] != 'location_relocation'
    ]


def test_an_earlier_movement_names_the_path_the_shelf_had_then(
    client, auth_headers, db_session, warehouses
):
    """A movement made before a physical move stands where the shelf stood then."""
    _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'physical')],
    )

    (earlier,) = _ledger(client, auth_headers, warehouses['flour'])
    assert earlier['to_location_id'] == str(warehouses['shelf'].id)
    assert earlier['to_location_path'] == 'Main Warehouse › Cold Storage › Shelf A'
    # Outside has no path, then or now.
    assert earlier['from_location_path'] is None

    # A movement made after the move stands where the tree puts it today,
    # which the row's own location already names.
    post_on_shelf(client, auth_headers, warehouses['flour'], warehouses['shelf'].id, 1)
    newest, _earlier = _ledger(client, auth_headers, warehouses['flour'])
    assert newest['to_location_path'] is None


def test_a_location_moved_twice_names_where_it_stood_at_each_movement(
    client, auth_headers, db_session, warehouses
):
    """Only the physical moves after a movement are undone, not every one."""
    _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'physical')],
    )
    _date_the_relocations(db_session, _TWO_WEEKS_AGO)
    post_on_shelf(client, auth_headers, warehouses['flour'], warehouses['shelf'].id, 1)
    db_session.execute(
        update(StockMove)
        .where(
            StockMove.product_template_id == warehouses['flour'].id,
            StockMove.completed_at > _A_WEEK_AGO,
        )
        .values(completed_at=_A_WEEK_AGO)
    )
    db_session.commit()
    _reorg(
        client,
        auth_headers,
        [_move(warehouses['shelf'], warehouses['empty'], 'physical')],
    )

    in_between, a_month_ago = _ledger(client, auth_headers, warehouses['flour'])
    assert in_between['to_location_path'] == 'Pantry Building › Cold Storage › Shelf A'
    assert a_month_ago['to_location_path'] == 'Main Warehouse › Cold Storage › Shelf A'


def test_a_movement_on_a_location_that_never_moved_keeps_todays_path(
    client, auth_headers, db_session, test_user, warehouses
):
    """A physical move of one shelf leaves every other place's history alone."""
    rice = _template(db_session, test_user, 'Rice')
    db_session.commit()
    post_on_shelf(client, auth_headers, rice, warehouses['empty'].id, 2)
    db_session.execute(
        update(StockMove)
        .where(StockMove.product_template_id == rice.id)
        .values(completed_at=_A_MONTH_AGO)
    )
    db_session.commit()
    _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'physical')],
    )

    (earlier,) = _ledger(client, auth_headers, rice)
    assert earlier['to_location_path'] is None


def test_the_stock_on_a_date_stands_where_the_location_stood_then(
    client, auth_headers, db_session, warehouses
):
    _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'physical')],
    )
    _date_the_relocations(db_session, _A_WEEK_AGO)
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
        'Main Warehouse › Cold Storage',
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


def _filtered_ledger(client, auth_headers, product, location) -> list[dict]:
    """The product's movements in *location*, without those a move wrote."""
    response = client.get(
        '/api/v1/stock-moves',
        headers=auth_headers,
        params={
            'product_template_id': str(product.id),
            'location_id': str(location.id),
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return [
        row
        for row in response.json()['items']
        if row['reference_type'] != 'location_relocation'
    ]


def test_filtering_by_a_location_reads_the_tree_each_movement_stood_in(
    client, auth_headers, db_session, warehouses
):
    """A movement belongs to the warehouse its shelf stood in when it happened."""
    _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'physical')],
    )
    # A month ago the shelf stood under Main Warehouse, not under Pantry.
    assert (
        len(
            _filtered_ledger(
                client, auth_headers, warehouses['flour'], warehouses['main']
            )
        )
        == 1
    )
    assert (
        _filtered_ledger(
            client, auth_headers, warehouses['flour'], warehouses['pantry']
        )
        == []
    )

    # Goods put on the shelf after the move belong to Pantry, not to Main.
    post_on_shelf(client, auth_headers, warehouses['flour'], warehouses['shelf'].id, 1)
    (after,) = _filtered_ledger(
        client, auth_headers, warehouses['flour'], warehouses['pantry']
    )
    assert after['to_location_id'] == str(warehouses['shelf'].id)
    assert (
        len(
            _filtered_ledger(
                client, auth_headers, warehouses['flour'], warehouses['main']
            )
        )
        == 1
    )


def test_filtering_by_a_location_that_moved_keeps_its_old_contents(
    client, auth_headers, db_session, warehouses
):
    """The moved location itself, and its shelf, list their whole history."""
    _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'physical')],
    )
    post_on_shelf(client, auth_headers, warehouses['flour'], warehouses['shelf'].id, 1)
    for place in (warehouses['cold'], warehouses['shelf']):
        assert (
            len(_filtered_ledger(client, auth_headers, warehouses['flour'], place)) == 2
        )


def _relocation_rows_in(client, auth_headers, product, location) -> list[dict]:
    response = client.get(
        '/api/v1/stock-moves',
        headers=auth_headers,
        params={
            'product_template_id': str(product.id),
            'location_id': str(location.id),
            'reference_type': 'location_relocation',
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()['items']


def test_the_row_a_physical_move_wrote_is_listed_under_both_places(
    client, auth_headers, db_session, warehouses
):
    """The move lists under the place the location left and the one it reached.

    Read under the old warehouse the goods came in and never went out unless
    the move's own row, naming the shelf in both places, is among them.
    """
    _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'physical')],
    )
    for place in (warehouses['main'], warehouses['pantry'], warehouses['cold']):
        rows = _relocation_rows_in(client, auth_headers, warehouses['flour'], place)
        assert len(rows) == 1, place.name
    # A place the location never stood in does not list it.
    assert (
        _relocation_rows_in(
            client, auth_headers, warehouses['flour'], warehouses['empty']
        )
        == []
    )


def _document_into(db_session, user, shelf, number, *, status, completed_at=None):
    from app.modules.warehouse.models.document import Document

    document = Document(
        organization_id=user.organization_id,
        type='IN',
        number=number,
        status=status,
        target_location_id=shelf.id,
        completed_at=completed_at,
        created_by=user.id,
    )
    db_session.add(document)
    db_session.flush()
    return document


def _documents_in(client, auth_headers, location) -> set[str]:
    response = client.get(
        '/api/v1/warehouse/documents',
        headers=auth_headers,
        params={'location_id': str(location.id), 'limit': 100},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return {row['number'] for row in response.json()['items']}


def test_a_completed_document_lists_under_the_place_its_shelf_stood_in(
    client, auth_headers, db_session, test_user, warehouses
):
    """A completed document belongs to where its shelf stood when it was done.

    An open document is work still to do, so it reads the tree as it is today.
    """
    done = _document_into(
        db_session,
        test_user,
        warehouses['shelf'],
        'IN/2026/901',
        status='COMPLETED',
        completed_at=_A_MONTH_AGO,
    )
    planned = _document_into(
        db_session, test_user, warehouses['shelf'], 'IN/2026/902', status='DRAFT'
    )
    db_session.commit()
    _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'physical')],
    )

    assert _documents_in(client, auth_headers, warehouses['main']) == {done.number}
    assert _documents_in(client, auth_headers, warehouses['pantry']) == {planned.number}
    # The moved place itself keeps both.
    assert _documents_in(client, auth_headers, warehouses['cold']) == {
        done.number,
        planned.number,
    }


def _todo_keys(client, auth_headers, location) -> set[str]:
    response = client.get(
        '/api/v1/warehouse/todo',
        headers=auth_headers,
        params={
            'location_id': str(location.id),
            'done_since': (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            'date_to': (datetime.now(UTC) + timedelta(days=7)).date().isoformat(),
            'limit': 100,
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return {item['key'] for item in response.json()['work_items']['items']}


def test_the_done_part_of_the_todo_reads_the_place_a_shelf_stood_in(
    client, auth_headers, db_session, test_user, warehouses
):
    """A document done before its shelf was carried stays under the old place.

    The queue filtered by a place lists the document under the place its shelf
    stood in when it was done; the work still open reads the tree as it is.
    """
    done = _document_into(
        db_session,
        test_user,
        warehouses['shelf'],
        'IN/2026/911',
        status='COMPLETED',
        completed_at=datetime.now(UTC) - timedelta(hours=1),
    )
    planned = _document_into(
        db_session, test_user, warehouses['shelf'], 'IN/2026/912', status='CONFIRMED'
    )
    db_session.commit()
    _reorg(
        client,
        auth_headers,
        [_move(warehouses['cold'], warehouses['pantry'], 'physical')],
    )
    done_key = f'document:{done.id}:receive'
    planned_key = f'document:{planned.id}:receive'

    main = _todo_keys(client, auth_headers, warehouses['main'])
    assert done_key in main
    assert planned_key not in main
    pantry = _todo_keys(client, auth_headers, warehouses['pantry'])
    assert done_key not in pantry
    assert planned_key in pantry
