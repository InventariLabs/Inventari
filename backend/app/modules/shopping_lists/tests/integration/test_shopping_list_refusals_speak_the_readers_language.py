"""The shopping list refusals answer in the reader's language.

A re-purchase, an edit of a finished list and a call into a disabled module
each raised an English sentence under a code of its own. Reverting a site to
its English literal keeps the status and the code, so the assertions are on
the Polish sentence.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.i18n import MAINTAINED_LANGUAGES
from app.i18n.service import get_error_message, set_current_lang
from app.models.user import User
from app.modules.shopping_lists import shopping_lists_api as facade
from app.modules.shopping_lists.models import ShoppingList, ShoppingListItem

pytestmark = pytest.mark.integration

NEW_KEYS = {
    'shopping_item_already_purchased',
    'shopping_item_already_purchased_reset',
    'shopping_list_not_editable',
    'shopping_lists_module_disabled',
}


@pytest.fixture
def test_shopping_list(db_session: Session, test_user: User) -> ShoppingList:
    shopping_list = ShoppingList(
        organization_id=test_user.organization_id,
        created_by=test_user.id,
        name='Refusals list',
    )
    db_session.add(shopping_list)
    db_session.commit()
    db_session.refresh(shopping_list)
    return shopping_list


@pytest.fixture
def test_shopping_list_item(
    db_session: Session, test_shopping_list: ShoppingList, test_category: Any
) -> ShoppingListItem:
    item = ShoppingListItem(
        shopping_list_id=test_shopping_list.id,
        name='Leeks',
        quantity=2,
        category_id=test_category.id,
        priority=0,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _polish(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, 'Accept-Language': 'pl'}


def test_purchasing_a_purchased_item_is_refused_in_polish(
    client: TestClient,
    auth_headers: dict[str, str],
    test_shopping_list_item: ShoppingListItem,
) -> None:
    url = (
        f'/api/v1/shopping-lists/{test_shopping_list_item.shopping_list_id}'
        f'/items/{test_shopping_list_item.id}/purchase'
    )
    assert client.patch(url, headers=auth_headers).status_code == status.HTTP_200_OK

    response = client.patch(url, headers=_polish(auth_headers))

    assert response.status_code == status.HTTP_409_CONFLICT
    detail = response.json()['detail']
    assert detail['code'] == 'ALREADY_PURCHASED'
    assert detail['message'] == (
        'Ta pozycja jest już oznaczona jako kupiona. '
        'Aby ją zmienić, najpierw oznacz ją jako niekupioną.'
    )


def test_editing_a_finished_list_is_refused_in_polish(
    client: TestClient,
    auth_headers: dict[str, str],
    test_shopping_list: ShoppingList,
    db_session: Session,
) -> None:
    test_shopping_list.status = 'completed'
    db_session.commit()

    response = client.put(
        f'/api/v1/shopping-lists/{test_shopping_list.id}',
        json={'name': 'Renamed'},
        headers=_polish(auth_headers),
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    detail = response.json()['detail']
    assert detail['code'] == 'SHOPPING_LIST_NOT_EDITABLE'
    assert (
        detail['message']
        == 'Nie można edytować ukończonej ani zarchiwizowanej listy zakupów.'
    )


@pytest.mark.asyncio
async def test_the_facade_of_a_disabled_module_refuses_in_polish(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    async def disabled(*_args: object) -> bool:
        return False

    monkeypatch.setattr('app.core.modules.is_module_enabled_async', disabled)
    set_current_lang('pl')
    try:
        with pytest.raises(PermissionError) as caught:
            await facade._require_module_enabled(db_session, uuid4())
    finally:
        set_current_lang('en')

    assert (
        str(caught.value) == 'Moduł list zakupów nie jest włączony dla tej organizacji.'
    )


@pytest.mark.parametrize('key', sorted(NEW_KEYS))
def test_every_new_key_is_translated_in_every_maintained_language(key: str) -> None:
    english = get_error_message(key, 'en')
    assert english != key
    for lang in MAINTAINED_LANGUAGES:
        if lang != 'en':
            assert get_error_message(key, lang) != english, (key, lang)
