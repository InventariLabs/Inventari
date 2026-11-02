"""An edit that gives a record its card puts the record's stock in the register.

``PUT /items/{id}`` writes the low-stock threshold and the unit weight to the
record's card, and a record that predates its card gets one on the way. That
door minted the card itself: a fresh row beside any card of the same name,
bound with no paper, and the stock the record already held left outside the
register it had just joined — the record said 4, the shelf said nothing, and
the reconciliation report named the drift until some later quantity edit
happened to heal it.

Every other door that gives a record its card adopts it one way — resolved or
minted from the record's own words, bound through the unit gate with a history
row, and the holding posted as an opening balance: the record's stock on its
shelf under the card, a movement saying where it came from, and the cost
layer behind it. The edit takes the same way now, so its card is the one a
receipt of the same product would have found, and the report's pairs agree
from the first write on.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.item_history import ItemAction, ItemHistory
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove, StockMoveReferenceType
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration

ITEM_URL = '/api/v1/items'


def _record_that_predates_its_card(
    db: Session, shelf: StorageLocation, name: str, quantity: str
) -> Item:
    """A record as it stands before any card: nothing about it in the register."""
    item = Item(
        organization_id=shelf.organization_id,
        storage_location_id=shelf.id,
        name=name,
        quantity=Decimal(quantity),
    )
    db.add(item)
    db.commit()
    return item


def _reconciliation(client, auth_headers) -> dict:
    response = client.get('/api/v1/stats/reconciliation', headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_edit_that_gives_a_card_opens_the_shelf_with_the_records_stock(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    item = _record_that_predates_its_card(
        db_session, test_storage_location, 'Jasmine Rice', '4'
    )

    response = client.put(
        f'{ITEM_URL}/{item.id}', headers=auth_headers, json={'min_quantity': 5}
    )

    assert response.status_code == 200, response.text
    card_id = response.json()['template_id']
    assert card_id is not None
    db_session.expire_all()
    on_shelf = db_session.scalar(
        select(func.sum(ShelfRow.quantity)).where(
            ShelfRow.product_template_id == card_id,
            ShelfRow.storage_location_id == test_storage_location.id,
        )
    )
    assert on_shelf == Decimal('4'), (
        'the record holds 4 and the shelf it stands on holds none of them'
    )
    moves = db_session.scalars(
        select(StockMove).where(StockMove.product_template_id == card_id)
    ).all()
    assert [
        (m.reference_type, m.quantity, m.to_location_id, m.reference_id) for m in moves
    ] == [
        (
            StockMoveReferenceType.OPENING_BALANCE,
            Decimal('4'),
            test_storage_location.id,
            item.id,
        )
    ]

    report = _reconciliation(client, auth_headers)
    assert report['quant_move_drift_count'] == 0, report
    assert report['layer_quant_drift_count'] == 0, report


def test_the_edit_joins_the_card_a_receipt_would_have_found(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    card = ProductTemplate(
        organization_id=test_storage_location.organization_id, name='Basmati'
    )
    db_session.add(card)
    db_session.commit()
    item = _record_that_predates_its_card(
        db_session, test_storage_location, 'Basmati', '3'
    )

    response = client.put(
        f'{ITEM_URL}/{item.id}', headers=auth_headers, json={'weight_value': 250}
    )

    assert response.status_code == 200, response.text
    assert response.json()['template_id'] == str(card.id), (
        'the edit minted a twin beside the card this product already has'
    )
    db_session.expire_all()
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ProductTemplate)
            .where(
                ProductTemplate.organization_id == card.organization_id,
                ProductTemplate.name == 'Basmati',
            )
        )
        == 1
    )
    assert db_session.get(ProductTemplate, card.id).weight_value == 250
    # The bind's own paper: the record's history names the card it joined.
    bound = [
        row.changes['new']['template_id']
        for row in db_session.scalars(
            select(ItemHistory).where(
                ItemHistory.item_id == item.id,
                ItemHistory.action == ItemAction.UPDATED.value,
            )
        )
        if 'template_id' in (row.changes or {}).get('new', {})
    ]
    assert bound == [str(card.id)]
