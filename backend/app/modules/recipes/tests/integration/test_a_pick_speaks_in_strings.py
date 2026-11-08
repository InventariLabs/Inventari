"""What a pick took, left and gives back crosses the wire as a string.

A stock quantity never travels as a JSON number (TECHNICAL_DECISIONS §18):
the reader of a float cannot tell an exact value from one rounded for
transport. The picking answers sent floats — and worked the shelf's
remainder out in floats too, so 0.3 kg less 0.1 kg came back as
0.19999999999999998 of a shelf. The tests look at the shape as well as the
value, because ``Decimal('0.2')`` compares equal to ``Decimal(0.2)`` only
when it is not one.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records

from .test_picking_unit_mismatch import RECIPE_URL, _recipe_in_grams, _uom_id

pytestmark = pytest.mark.integration


def _flour_in_kilograms(
    db: Session, user: User, location: StorageLocation, kilograms: str
) -> tuple[ProductTemplate, Item]:
    kg = _uom_id(db, 'kg')
    template = ProductTemplate(
        id=uuid.uuid4(), organization_id=user.organization_id, name='Flour', uom_id=kg
    )
    db.add(template)
    db.flush()
    item = Item(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        storage_location_id=location.id,
        name='Flour',
        template_id=template.id,
        uom_id=kg,
        quantity=Decimal(kilograms),
    )
    db.add(item)
    anchor_pending_records(db)
    db.commit()
    return template, item


def _pick(
    client: TestClient, headers: dict[str, str], recipe_id: str, item: Item
) -> tuple[str, dict[str, Any]]:
    start = client.post(
        f'{RECIPE_URL}/{recipe_id}/picking/start',
        json={'servings': 1},
        headers=headers,
    )
    assert start.status_code == 201, start.text
    session_id = str(start.json()['picking_session_id'])
    scan = client.post(
        f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
        json={'item_id': str(item.id)},
        headers=headers,
    )
    assert scan.status_code == 200, scan.text
    return session_id, scan.json()


def _quantity(value: object) -> Decimal:
    assert isinstance(value, str), f'{value!r} crossed the wire as a number'
    return Decimal(value)


class TestAPickSpeaksInStrings:
    def test_a_partial_pick_and_its_undo_answer_in_strings(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """300 g on the shelf for a recipe asking 500 g: all of it, 200 g short."""
        template, item = _flour_in_kilograms(
            db_session, test_user, test_storage_location, '0.3'
        )
        recipe_id = _recipe_in_grams(client, auth_headers, db_session, template)

        session_id, body = _pick(client, auth_headers, recipe_id, item)

        assert body['status'] == 'picked', body
        assert _quantity(body['quantity_consumed']) == Decimal('300')
        assert _quantity(body['item_remaining_quantity']) == Decimal('0')
        assert _quantity(body['ingredient_remaining_quantity']) == Decimal('200')

        undo = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/undo',
            json={'ingredient_id': body['ingredient_id']},
            headers=auth_headers,
        )
        assert undo.status_code == 200, undo.text
        # Undo reports what it gave back in the recipe's unit, the one it names.
        assert _quantity(undo.json()['restored_quantity']) == Decimal('300')
        assert undo.json()['uom_symbol'] == 'g'

    def test_what_is_left_on_the_shelf_is_the_number_written_there(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """100 g taken from 0.3 kg leaves 0.2 kg, not 0.19999999999999998."""
        template, item = _flour_in_kilograms(
            db_session, test_user, test_storage_location, '0.3'
        )
        recipe_id = _recipe_in_grams(
            client, auth_headers, db_session, template, grams='100'
        )

        _, body = _pick(client, auth_headers, recipe_id, item)

        assert body['status'] == 'picked', body
        assert _quantity(body['item_remaining_quantity']) == Decimal('0.2')
        assert body['ingredient_remaining_quantity'] is None
