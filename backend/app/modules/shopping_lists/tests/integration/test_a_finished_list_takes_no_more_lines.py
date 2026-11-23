"""A finished list takes no more changes to its lines.

The page hides the tick, the quantity and the delete on a completed or
archived list and says nothing there can be changed. The server holds the
same rule: every endpoint that adds, edits, ticks or removes a line asks
``_require_writable_list`` first, so a stale tab or an API client gets the
refusal the screen promised instead of a write the frozen list accepted.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.user import User
from app.modules.shopping_lists.models import ShoppingList, ShoppingListItem

pytestmark = pytest.mark.integration


@pytest.fixture
def finished_list(db_session: Session, test_user: User) -> ShoppingList:
    shopping_list = ShoppingList(
        organization_id=test_user.organization_id,
        created_by=test_user.id,
        name='A finished list',
        status='completed',
    )
    db_session.add(shopping_list)
    db_session.commit()
    db_session.refresh(shopping_list)
    return shopping_list


@pytest.fixture
def line(
    db_session: Session, finished_list: ShoppingList, test_category: Any
) -> ShoppingListItem:
    item = ShoppingListItem(
        shopping_list_id=finished_list.id,
        name='Leeks',
        quantity=2,
        category_id=test_category.id,
        priority=0,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _assert_not_editable(response: Any) -> None:
    assert response.status_code == status.HTTP_409_CONFLICT, response.text
    assert response.json()['detail']['code'] == 'SHOPPING_LIST_NOT_EDITABLE'


def test_editing_a_line_of_a_finished_list_is_refused(
    client: TestClient,
    auth_headers: dict[str, str],
    finished_list: ShoppingList,
    line: ShoppingListItem,
) -> None:
    response = client.put(
        f'/api/v1/shopping-lists/{finished_list.id}/items/{line.id}',
        json={'quantity': 900},
        headers=auth_headers,
    )

    _assert_not_editable(response)


def test_ticking_a_line_of_a_finished_list_is_refused(
    client: TestClient,
    auth_headers: dict[str, str],
    finished_list: ShoppingList,
    line: ShoppingListItem,
) -> None:
    response = client.patch(
        f'/api/v1/shopping-lists/{finished_list.id}/items/{line.id}/purchase',
        headers=auth_headers,
    )

    _assert_not_editable(response)


def test_unticking_a_line_of_a_finished_list_is_refused(
    client: TestClient,
    auth_headers: dict[str, str],
    finished_list: ShoppingList,
    line: ShoppingListItem,
) -> None:
    response = client.patch(
        f'/api/v1/shopping-lists/{finished_list.id}/items/{line.id}/unpurchase',
        headers=auth_headers,
    )

    _assert_not_editable(response)


def test_deleting_a_line_of_a_finished_list_is_refused(
    client: TestClient,
    auth_headers: dict[str, str],
    finished_list: ShoppingList,
    line: ShoppingListItem,
) -> None:
    response = client.delete(
        f'/api/v1/shopping-lists/{finished_list.id}/items/{line.id}',
        headers=auth_headers,
    )

    _assert_not_editable(response)


def test_clearing_the_purchased_lines_of_a_finished_list_is_refused(
    client: TestClient,
    auth_headers: dict[str, str],
    finished_list: ShoppingList,
) -> None:
    response = client.delete(
        f'/api/v1/shopping-lists/{finished_list.id}/items/purchased',
        headers=auth_headers,
    )

    _assert_not_editable(response)


def test_adding_the_suggestions_to_a_finished_list_is_refused(
    client: TestClient,
    auth_headers: dict[str, str],
    finished_list: ShoppingList,
) -> None:
    response = client.post(
        f'/api/v1/shopping-lists/{finished_list.id}/suggestions/add-all',
        headers=auth_headers,
    )

    _assert_not_editable(response)
