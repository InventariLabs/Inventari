"""Stock past its date is not stock to cook with.

Measured on a demo kitchen: the only chicken on the shelf had gone off two
days earlier, and the recipe showed the ingredient with a green dot, the
fridge it sat in, and an orange "Short shelf life" beside a date that had
already passed. FEFO took the earliest date and never asked whether it was
still ahead — so with a fresh pack beside the spoiled one, the spoiled one
was the pick, and with only spoiled ones the recipe counted as cookable.

The rule is the core's (``services/items/expiry.py``): an item is past its
date the day after the date, measured on the organization's day. What is
past it does not count towards what the recipe needs, is never recommended
while something fresh is there, and is named for what it is when it is all
there is.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records

RECIPE_URL = '/api/v1/recipes'

pytestmark = pytest.mark.integration


def _grams(db: Session) -> uuid.UUID:
    row = db.execute(text("SELECT id FROM uoms WHERE symbol = 'g'")).fetchone()
    assert row is not None, "'g' is not seeded"
    return uuid.UUID(str(row[0]))


def _shelve(
    db: Session,
    user: User,
    location: StorageLocation,
    packs: list[tuple[date, str]],
) -> list[uuid.UUID]:
    """Packs of one product, each with its own date and weight in grams."""
    grams = _grams(db)
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        name='Chicken breast',
        uom_id=grams,
    )
    db.add(template)
    db.flush()
    ids = []
    for expiry, weight in packs:
        item = Item(
            id=uuid.uuid4(),
            organization_id=user.organization_id,
            storage_location_id=location.id,
            name='Chicken breast',
            template_id=template.id,
            uom_id=grams,
            quantity=Decimal(weight),
            expiry_date=expiry,
        )
        db.add(item)
        ids.append(item.id)
    anchor_pending_records(db)
    db.commit()
    return ids


def _curry(client: TestClient, auth_headers: dict[str, str], db: Session) -> str:
    response = client.post(
        RECIPE_URL,
        json={
            'name': 'Chicken curry',
            'servings': 1,
            'instructions': 'Cook.',
            'ingredients': [
                {
                    'name': 'Chicken breast',
                    'quantity': '300',
                    'uom_id': str(_grams(db)),
                    'is_optional': False,
                }
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


def _availability(
    client: TestClient, auth_headers: dict[str, str], recipe_id: str
) -> dict[str, Any]:
    response = client.get(
        f'{RECIPE_URL}/{recipe_id}/availability', headers=auth_headers
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def _checklist(
    client: TestClient, auth_headers: dict[str, str], recipe_id: str
) -> dict[str, Any]:
    response = client.post(
        f'{RECIPE_URL}/{recipe_id}/picking/start',
        json={'servings': 1},
        headers=auth_headers,
    )
    assert response.status_code in (200, 201), response.text
    [row] = response.json()['items_to_pick']
    return dict(row)


class TestTheRecipeSaysWhatIsFitToCook:
    def test_an_ingredient_whose_only_stock_is_past_its_date_is_not_available(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """Measured on dev: 'available_approx', a green dot, the recipe
        counted as cookable."""
        went_off = date.today() - timedelta(days=2)
        _shelve(db_session, test_user, test_storage_location, [(went_off, '500')])
        recipe_id = _curry(client, auth_headers, db_session)

        availability = _availability(client, auth_headers, recipe_id)

        [row] = availability['ingredients']
        assert row['status'] == 'missing'
        assert availability['match_percentage'] == 0
        # Still said, and said for what it is: the pack is there, in the
        # fridge, and past its date — not missing without a word.
        assert row['best_item']['expired'] is True
        assert row['best_item']['expiry_date'] == went_off.isoformat()
        assert row['best_item']['fefo_days_left'] is None

    def test_a_fresh_pack_is_the_pick_over_one_past_its_date(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """Measured on dev: the spoiled pack was the pick, and its 500 g
        covered the 300 g the recipe asks for."""
        went_off = date.today() - timedelta(days=2)
        fresh_until = date.today() + timedelta(days=10)
        _shelve(
            db_session,
            test_user,
            test_storage_location,
            [(went_off, '500'), (fresh_until, '200')],
        )
        recipe_id = _curry(client, auth_headers, db_session)

        [row] = _availability(client, auth_headers, recipe_id)['ingredients']

        assert row['best_item']['expiry_date'] == fresh_until.isoformat()
        assert row['best_item']['expired'] is False
        assert row['status'] == 'insufficient'
        assert row['available_quantity'] == 200

    def test_short_shelf_life_is_never_said_of_a_date_gone_by(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """Measured on dev: ``fefo_days_left`` -3, which the screen reads as
        "Short shelf life" beside a date three days gone."""
        today = date.today()
        _shelve(
            db_session,
            test_user,
            test_storage_location,
            [(today - timedelta(days=3), '200'), (today - timedelta(days=2), '200')],
        )
        recipe_id = _curry(client, auth_headers, db_session)

        [row] = _availability(client, auth_headers, recipe_id)['ingredients']

        assert row['best_item']['fefo_days_left'] is None
        assert row['best_item']['expired'] is True


class TestPickingTakesTheFreshPack:
    def test_the_checklist_recommends_the_fresh_pack(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """Measured on dev: the recommended item was the spoiled one."""
        _, fresh = _shelve(
            db_session,
            test_user,
            test_storage_location,
            [
                (date.today() - timedelta(days=2), '500'),
                (date.today() + timedelta(days=10), '400'),
            ],
        )
        recipe_id = _curry(client, auth_headers, db_session)

        row = _checklist(client, auth_headers, recipe_id)

        assert row['recommended_item_id'] == str(fresh)
        assert row['status'] == 'pending'

    def test_an_ingredient_with_only_stock_past_its_date_is_missing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """The checklist agrees with the recipe: nothing on it to take."""
        _shelve(
            db_session,
            test_user,
            test_storage_location,
            [(date.today() - timedelta(days=2), '500')],
        )
        recipe_id = _curry(client, auth_headers, db_session)

        row = _checklist(client, auth_headers, recipe_id)

        assert row['status'] == 'missing'
        assert row['recommended_item_id'] is None
