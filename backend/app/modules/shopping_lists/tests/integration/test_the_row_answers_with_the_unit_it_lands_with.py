"""A row saved with a unit answers with that unit — not a 500, not a stale one.

Adding a list row that names a unit ended in a 500 with the row saved: the
write path returned the freshly constructed ORM object, whose ``uom``
relationship nothing had loaded, and the response schema reads it — the
serialization lazy-load outside the greenlet took the response down. The
read path never noticed because ``lazy='joined'`` loads the unit on every
query; only the doors that answer with the object they just built were
blind to it. The bulk door carried the same blind spot, and the edit door
answered 200 with the unit the row used to wear.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.uom import Uom, UomCategory
from app.modules.shopping_lists.models import ShoppingList

pytestmark = pytest.mark.integration


@pytest.fixture
def test_shopping_list(db_session: Session, test_user: Any) -> ShoppingList:
    shopping_list = ShoppingList(
        organization_id=test_user.organization_id,
        created_by=test_user.id,
        name='Unit list',
    )
    db_session.add(shopping_list)
    db_session.commit()
    db_session.refresh(shopping_list)
    return shopping_list


@pytest.fixture
def weight_uoms(db_session: Session, test_user: Any) -> dict[str, Uom]:
    """A category with two units the row can wear: kilograms and grams."""
    category = UomCategory(organization_id=test_user.organization_id, name='Mass')
    db_session.add(category)
    db_session.flush()
    kilo = Uom(
        organization_id=test_user.organization_id,
        category_id=category.id,
        name='kilogram',
        symbol='kg',
        is_reference=True,
    )
    gram = Uom(
        organization_id=test_user.organization_id,
        category_id=category.id,
        name='gram',
        symbol='g',
    )
    db_session.add_all([kilo, gram])
    db_session.commit()
    db_session.refresh(kilo)
    db_session.refresh(gram)
    return {'kg': kilo, 'g': gram}


@pytest.mark.integration
class TestTheRowAnswersWithItsUnit:
    def test_adding_a_row_with_a_unit_answers_201_and_names_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
        weight_uoms: dict[str, Uom],
    ) -> None:
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={
                'name': 'Mąka',
                'quantity': 2,
                'uom_id': str(weight_uoms['kg'].id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['uom_id'] == str(weight_uoms['kg'].id)
        assert data['uom']['symbol'] == 'kg'

    def test_a_bulk_of_rows_answers_each_with_its_own_unit(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
        weight_uoms: dict[str, Uom],
    ) -> None:
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items/bulk',
            headers=auth_headers,
            json=[
                {
                    'name': 'Mąka',
                    'quantity': 2,
                    'uom_id': str(weight_uoms['kg'].id),
                },
                {
                    'name': 'Cukier',
                    'quantity': 500,
                    'uom_id': str(weight_uoms['g'].id),
                },
            ],
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        units = {row['name']: (row['uom'] or {}).get('symbol') for row in data}
        assert units['Mąka'] == 'kg'
        assert units['Cukier'] == 'g'

    def test_changing_the_unit_answers_with_the_new_one(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
        weight_uoms: dict[str, Uom],
    ) -> None:
        add_response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={
                'name': 'Mąka',
                'quantity': 2,
                'uom_id': str(weight_uoms['kg'].id),
            },
        )
        assert add_response.status_code == status.HTTP_201_CREATED
        row_id = add_response.json()['id']

        edit_response = client.put(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items/{row_id}',
            headers=auth_headers,
            json={
                'name': 'Mąka',
                'quantity': 2,
                'uom_id': str(weight_uoms['g'].id),
            },
        )

        assert edit_response.status_code == status.HTTP_200_OK
        data = edit_response.json()
        assert data['uom_id'] == str(weight_uoms['g'].id)
        assert data['uom']['symbol'] == 'g'

    def test_a_row_without_a_unit_still_answers(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """Most rows carry no unit — the door stays open for them."""
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Chleb', 'quantity': 1},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['uom'] is None
