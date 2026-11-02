"""What "I can cook" answers has to be cookable.

The endpoint behind that tab passed anything at least half covered, so a
recipe missing two ingredients of four came back as available and the card
beside it read "2 of 4 in stock". The heading is the part people act on: they
choose the meal instead of checking the cupboard, and find out at the bowl.

The near misses still have a reader, so they are still reachable — by asking
for them, at a threshold the screen names.
"""

from __future__ import annotations

import uuid
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


def _uom_id(db: Session, symbol: str) -> uuid.UUID:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'UOM {symbol!r} is not seeded'
    return uuid.UUID(str(row[0]))


def _put_on_the_shelf(
    db: Session,
    user: User,
    location: StorageLocation,
    name: str,
    grams: str,
) -> None:
    grams_uom = _uom_id(db, 'g')
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        name=name,
        uom_id=grams_uom,
    )
    db.add(template)
    db.flush()
    db.add(
        Item(
            id=uuid.uuid4(),
            organization_id=user.organization_id,
            storage_location_id=location.id,
            name=name,
            template_id=template.id,
            uom_id=grams_uom,
            quantity=Decimal(grams),
        )
    )
    anchor_pending_records(db)
    db.commit()


def _recipe_of(
    client: TestClient,
    auth_headers: dict[str, str],
    db: Session,
    name: str,
    ingredients: list[str],
) -> str:
    payload = {
        'name': name,
        'servings': 1,
        'instructions': 'Mix.',
        'ingredients': [
            {
                'name': ingredient,
                'quantity': '100',
                'uom_id': str(_uom_id(db, 'g')),
                'is_optional': False,
            }
            for ingredient in ingredients
        ],
    }
    response = client.post(RECIPE_URL, json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


def _available(
    client: TestClient, auth_headers: dict[str, str], query: str = ''
) -> list[dict[str, Any]]:
    response = client.get(f'{RECIPE_URL}/available{query}', headers=auth_headers)
    assert response.status_code == 200, response.text
    return list(response.json()['items'])


@pytest.fixture
def half_stocked_kitchen(
    client: TestClient,
    auth_headers: dict[str, str],
    test_user: User,
    test_storage_location: StorageLocation,
    db_session: Session,
) -> dict[str, str]:
    """One recipe fully covered, one at half — nothing else on the shelf."""
    _put_on_the_shelf(db_session, test_user, test_storage_location, 'Flour', '1000')
    _put_on_the_shelf(db_session, test_user, test_storage_location, 'Butter', '500')
    return {
        'cookable': _recipe_of(
            client, auth_headers, db_session, 'Shortcrust', ['Flour', 'Butter']
        ),
        'half': _recipe_of(
            client, auth_headers, db_session, 'Custard', ['Flour', 'Vanilla pod']
        ),
    }


def test_half_a_recipe_is_not_an_answer_to_what_can_i_cook(
    client: TestClient,
    auth_headers: dict[str, str],
    half_stocked_kitchen: dict[str, str],
) -> None:
    ids = [recipe['id'] for recipe in _available(client, auth_headers)]

    assert half_stocked_kitchen['cookable'] in ids
    assert half_stocked_kitchen['half'] not in ids


def test_the_near_misses_are_still_reachable_by_asking(
    client: TestClient,
    auth_headers: dict[str, str],
    half_stocked_kitchen: dict[str, str],
) -> None:
    """The looser reading is a request, not a default nobody can see."""
    recipes = _available(client, auth_headers, '?min_match=0.5')
    by_id = {recipe['id']: recipe for recipe in recipes}

    assert half_stocked_kitchen['half'] in by_id
    assert by_id[half_stocked_kitchen['half']]['match_percentage'] == pytest.approx(
        0.5, abs=0.01
    )
