"""An unknown uom_id is a named refusal, not a raw foreign-key 500.

The unit selector in the UI offers only real units, but the API is
reachable by integrations, import scripts and external tests — every
caller that assembles its own request.  A random UUID as uom_id used to
hit the database and die on ``shopping_list_items_uom_id_fkey`` with a
bare 500.  The write layer now refuses before the row is built, naming
the field.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

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
        name='UoM refusal list',
    )
    db_session.add(shopping_list)
    db_session.commit()
    db_session.refresh(shopping_list)
    return shopping_list


@pytest.fixture
def weight_uom(db_session: Session, test_user: Any) -> Uom:
    """A real unit the row can wear — the control for the happy path."""
    category = UomCategory(organization_id=test_user.organization_id, name='Mass')
    db_session.add(category)
    db_session.flush()
    uom = Uom(
        organization_id=test_user.organization_id,
        category_id=category.id,
        name='kilogram',
        symbol='kg',
        is_reference=True,
    )
    db_session.add(uom)
    db_session.commit()
    db_session.refresh(uom)
    return uom


class TestAnUnknownUnitIsRefusedNotA500:
    def test_post_with_unknown_uom_is_a_named_refusal(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Mystery', 'quantity': 1, 'uom_id': str(uuid4())},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert 'uom_id' in response.text

    def test_put_with_unknown_uom_is_a_named_refusal(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
        weight_uom: Uom,
    ) -> None:
        item_id = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Flour', 'quantity': 1, 'uom_id': str(weight_uom.id)},
        ).json()['id']

        response = client.put(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items/{item_id}',
            headers=auth_headers,
            json={'uom_id': str(uuid4())},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert 'uom_id' in response.text

    def test_bulk_with_unknown_uom_is_a_named_refusal(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items/bulk',
            headers=auth_headers,
            json=[
                {'name': 'Good', 'quantity': 1},
                {'name': 'Bad', 'quantity': 1, 'uom_id': str(uuid4())},
            ],
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert 'uom_id' in response.text

    def test_a_real_unit_still_lands(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
        weight_uom: Uom,
    ) -> None:
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Flour', 'quantity': 2, 'uom_id': str(weight_uom.id)},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['uom_id'] == str(weight_uom.id)

    def test_no_unit_still_lands(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Bread', 'quantity': 1},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['uom_id'] is None

    def test_the_list_still_reads_after_the_refusals(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        response = client.get(
            f'/api/v1/shopping-lists/{test_shopping_list.id}',
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
