"""Cooking the last of a record leaves the lists, like using it up by hand.

Removing the last unit of a record files it under the virtual Consumed place,
so the products list, the overview's attention list and the counters stop
showing it. A pick that takes the last of a record did the same quantity
change without the filing, and the emptied record stayed on the list at 0
and was counted as needing attention. Undoing the pick gives the stock back
to the record, which returns to the shelf it left.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records

RECIPE_URL = '/api/v1/recipes'

pytestmark = pytest.mark.integration


def _uom_id(db: Session, symbol: str) -> uuid.UUID:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


def _milk_and_recipe(
    client: TestClient,
    auth_headers: dict[str, str],
    db: Session,
    user: User,
    shelf: StorageLocation,
) -> tuple[Item, str]:
    """One litre of milk on a shelf and a recipe that takes all of it."""
    litre = _uom_id(db, 'l')
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        name='Milk',
        uom_id=litre,
    )
    db.add(template)
    db.flush()
    item = Item(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        storage_location_id=shelf.id,
        name='Milk',
        template_id=template.id,
        uom_id=litre,
        quantity=Decimal('1'),
    )
    db.add(item)
    anchor_pending_records(db)
    db.commit()
    created = client.post(
        RECIPE_URL,
        json={
            'name': 'Porridge',
            'servings': 1,
            'instructions': 'Stir.',
            'ingredients': [
                {
                    'name': 'Milk',
                    'template_id': str(template.id),
                    'quantity': '1',
                    'uom_id': str(litre),
                    'is_optional': False,
                }
            ],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    return item, str(created.json()['id'])


def _where(db: Session, item_id: uuid.UUID) -> tuple[Decimal, str]:
    db.expire_all()
    item = db.execute(select(Item).where(Item.id == item_id)).scalar_one()
    place = db.execute(
        select(StorageLocation).where(StorageLocation.id == item.storage_location_id)
    ).scalar_one()
    return Decimal(item.quantity), place.usage


class TestAPickThatEmptiesARecordFilesItAsUsedUp:
    def test_the_emptied_record_leaves_the_products_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item, recipe_id = _milk_and_recipe(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start.json()['picking_session_id']

        scan = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item.id)},
            headers=auth_headers,
        )

        assert scan.status_code == 200, scan.text
        assert scan.json()['status'] == 'picked'
        quantity, usage = _where(db_session, item.id)
        assert quantity == 0
        assert usage == LocationUsage.CUSTOMER
        listed = client.get('/api/v1/items', headers=auth_headers).json()['items']
        assert str(item.id) not in {row['id'] for row in listed}

        # Taking the pick back gives the litre to the record, on its shelf.
        undo = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/undo',
            json={'ingredient_id': scan.json()['ingredient_id']},
            headers=auth_headers,
        )
        assert undo.status_code == 200, undo.text
        quantity, _ = _where(db_session, item.id)
        db_session.refresh(item)
        assert quantity == 1
        assert item.storage_location_id == test_storage_location.id
