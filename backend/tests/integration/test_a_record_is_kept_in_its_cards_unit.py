"""A record is kept in its card's unit; a quantity named in another is converted.

A movement and a cost layer carry a number and no unit, and the records'
view — the shelf — sums ``items.quantity`` as it stands. So the only unit any
of them can mean is the card's. A record confirmed in grams on a card kept in
kilograms used to be written as it was named — 500 on the record, and 500 on
the shelf and in the ledger, where it read as 500 kg.

The rule every stock system keeps instead is that a product names one stock
unit and every entry is converted into it on the way in. The confirmation
stays: it is what stops a picker left on grams from the previous product.
What changes is its effect — the quantity is restated in the card's unit,
the unit price with it, and the record's history keeps what was entered.

Pieces meet a weight or a volume through what one piece measures, which the
card keeps (ADR-015). A card that does not say is refused by name, and so is
a pack: a pack is not a piece, and the card's measure is a piece's.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.i18n.service import get_default_language, get_error_message
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.stock_move import StockMove
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.uom import Uom

pytestmark = pytest.mark.integration

ITEMS_URL = '/api/v1/items'
TEMPLATES_URL = '/api/v1/items/product-templates'

REASON = 'unit_chosen_over_template'


def _uom(db: Session, symbol: str) -> Uom:
    uom = db.scalars(select(Uom).where(Uom.symbol == symbol)).first()
    assert uom is not None, f"'{symbol}' is not in the seeded catalogue"
    return uom


def _card(
    client: TestClient, headers: dict[str, str], name: str, uom: Uom, **measure
) -> str:
    response = client.post(
        TEMPLATES_URL,
        headers=headers,
        json={'name': name, 'uom_id': str(uom.id), **measure},
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return response.json()['id']


def _record(
    client: TestClient,
    headers: dict[str, str],
    storage: StorageLocation,
    name: str,
    quantity: str,
    uom: Uom,
    **extra,
):
    return client.post(
        ITEMS_URL,
        headers=headers,
        json={
            'name': name,
            'location_id': str(storage.id),
            'quantity': quantity,
            'uom_id': str(uom.id),
            'unit_confirmed_over_template': True,
            **extra,
        },
    )


def _shelf(db: Session, card_id: str) -> dict[str, Decimal]:
    """What each reader of the stock says the card holds."""
    db.expire_all()
    view = db.scalar(
        select(func.sum(stock_quants_from_records.c.quantity)).where(
            stock_quants_from_records.c.product_template_id == card_id
        )
    )
    moves = db.scalar(
        select(func.sum(StockMove.quantity)).where(
            StockMove.product_template_id == card_id
        )
    )
    layers = db.scalar(
        select(func.sum(StockValuationLayer.quantity)).where(
            StockValuationLayer.product_template_id == card_id
        )
    )
    return {'view': view, 'move': moves, 'layer': layers}


def _unit_choice_rows(db: Session, item_id) -> list[dict]:
    db.expire_all()
    return [
        row.changes
        for row in db.scalars(
            select(ItemHistory).where(ItemHistory.item_id == item_id)
        ).all()
        if (row.changes or {}).get('reason') == REASON
    ]


class TestAConvertibleUnitIsRestatedInTheCardsUnit:
    def test_grams_on_a_card_kept_in_kilograms_land_as_kilograms(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """Half a kilo, everywhere — not five hundred kilos anywhere."""
        kg, g = _uom(db_session, 'kg'), _uom(db_session, 'g')
        card_id = _card(client, auth_headers, 'Rye flour', kg)

        response = _record(
            client, auth_headers, test_storage_location, 'Rye flour', '500', g
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        db_session.expire_all()
        record = db_session.get(Item, response.json()['id'])
        assert record is not None
        assert (record.quantity, record.uom_id) == (Decimal('0.500'), kg.id)
        assert _shelf(db_session, card_id) == {
            'view': Decimal('0.500'),
            'move': Decimal('0.500'),
            'layer': Decimal('0.500'),
        }

    def test_the_unit_price_is_restated_with_the_quantity(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """A price per 100 g is ten times that per kilogram; the value holds.

        The record's price is a rate per its unit, and the cost layer takes
        it as a rate per the card's. Carried across unconverted, 2.50 for
        each 100 g became 2.50 for each kilogram — a quarter of the value.
        """
        kg = _uom(db_session, 'kg')
        g = _uom(db_session, 'g')
        card_id = _card(client, auth_headers, 'Saffron', kg)

        response = _record(
            client,
            auth_headers,
            test_storage_location,
            'Saffron',
            '200',
            g,
            purchase_price='0.25',
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        db_session.expire_all()
        record = db_session.get(Item, response.json()['id'])
        assert record is not None
        assert (record.quantity, record.purchase_price) == (
            Decimal('0.200'),
            Decimal('250.00'),
        )
        layer = db_session.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == card_id
            )
        ).one()
        assert layer.quantity * layer.unit_cost == Decimal('50.00')

    def test_the_history_keeps_what_was_entered(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """The record says 0.5 kg; its history says somebody typed 500 g."""
        kg, g = _uom(db_session, 'kg'), _uom(db_session, 'g')
        _card(client, auth_headers, 'Rye flour', kg)

        response = _record(
            client, auth_headers, test_storage_location, 'Rye flour', '500', g
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert _unit_choice_rows(db_session, response.json()['id']) == [
            {
                'reason': REASON,
                'template_uom': 'kg',
                'template_uom_name': 'Kilogram',
                'chosen_uom': 'g',
                'chosen_uom_name': 'Gram',
                'entered_quantity': '500.000',
                'kept_quantity': '0.500',
            }
        ]


class TestPiecesMeetAMeasureThroughTheCard:
    def test_pieces_on_a_card_kept_in_kilograms_are_weighed_by_the_card(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """Three loaves of 250 g are 0.75 kg of bread."""
        kg, g, pcs = (_uom(db_session, s) for s in ('kg', 'g', 'pcs'))
        card_id = _card(
            client,
            auth_headers,
            'Bread',
            kg,
            weight_value=250,
            weight_uom_id=str(g.id),
        )

        response = _record(
            client, auth_headers, test_storage_location, 'Bread', '3', pcs
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert _shelf(db_session, card_id)['view'] == Decimal('0.750')
        record = db_session.get(Item, response.json()['id'])
        assert record is not None and record.uom_id == kg.id

    def test_a_weight_on_a_card_counted_in_pieces_is_counted_by_the_card(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """A kilo of 250 g apples is four apples, on a card that counts them."""
        kg, g, pcs = (_uom(db_session, s) for s in ('kg', 'g', 'pcs'))
        card_id = _card(
            client,
            auth_headers,
            'Apple',
            pcs,
            weight_value=250,
            weight_uom_id=str(g.id),
        )

        response = _record(
            client, auth_headers, test_storage_location, 'Apple', '1', kg
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert _shelf(db_session, card_id)['view'] == Decimal('4.000')

    def test_pieces_on_a_card_that_does_not_say_what_one_weighs_are_refused(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """Nothing converts three pieces into kilograms, so nothing is written."""
        kg, pcs = _uom(db_session, 'kg'), _uom(db_session, 'pcs')
        _card(client, auth_headers, 'Rye flour', kg)

        response = _record(
            client, auth_headers, test_storage_location, 'Rye flour', '3', pcs
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        assert response.json()['detail']['message'] == get_error_message(
            'item_unit_not_convertible_to_card',
            get_default_language(),
            product='Rye flour',
            template_unit='kg',
            chosen_unit='pcs',
        )
        db_session.expire_all()
        assert (
            db_session.scalars(select(Item).where(Item.name == 'Rye flour')).first()
            is None
        )

    def test_a_pack_is_not_a_piece(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """The card's measure is one piece's, and a pack holds an unknown number."""
        kg, g, pack = (_uom(db_session, s) for s in ('kg', 'g', 'pack'))
        _card(
            client,
            auth_headers,
            'Bread',
            kg,
            weight_value=250,
            weight_uom_id=str(g.id),
        )

        response = _record(
            client, auth_headers, test_storage_location, 'Bread', '2', pack
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text


class TestTheEditsAnswerTheSameWay:
    def _empty_record(
        self,
        client: TestClient,
        headers: dict[str, str],
        storage: StorageLocation,
        kg: Uom,
    ) -> str:
        response = client.post(
            ITEMS_URL,
            headers=headers,
            json={
                'name': 'Rye flour',
                'location_id': str(storage.id),
                'quantity': 0,
                'uom_id': str(kg.id),
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        return response.json()['id']

    def test_an_edit_in_grams_is_kept_in_kilograms(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        kg, g = _uom(db_session, 'kg'), _uom(db_session, 'g')
        item_id = self._empty_record(client, auth_headers, test_storage_location, kg)

        response = client.put(
            f'{ITEMS_URL}/{item_id}',
            headers=auth_headers,
            json={
                'quantity': '500',
                'uom_id': str(g.id),
                'unit_confirmed_over_template': True,
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        db_session.expire_all()
        record = db_session.get(Item, item_id)
        assert record is not None
        assert (record.quantity, record.uom_id) == (Decimal('0.500'), kg.id)
        assert _shelf(db_session, str(record.template_id))['view'] == Decimal('0.500')
        assert [
            row['entered_quantity'] for row in _unit_choice_rows(db_session, item_id)
        ] == ['500.000']

    def test_a_batch_edit_in_grams_is_kept_in_kilograms(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        kg, g = _uom(db_session, 'kg'), _uom(db_session, 'g')
        item_id = self._empty_record(client, auth_headers, test_storage_location, kg)

        response = client.patch(
            f'{ITEMS_URL}/bulk',
            headers=auth_headers,
            json={
                'item_ids': [item_id],
                'update_data': {
                    'quantity': '500',
                    'uom_id': str(g.id),
                    'unit_confirmed_over_template': True,
                },
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        db_session.expire_all()
        record = db_session.get(Item, item_id)
        assert record is not None
        assert (record.quantity, record.uom_id) == (Decimal('0.500'), kg.id)
