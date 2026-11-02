"""An unknown category_id, item_id or template_id is a named refusal, not a raw 500.

The pickers in the UI offer only real cards, but the API is reachable by
integrations, import scripts and external tests — every caller that
assembles its own request. A random UUID in any of the three product
reference columns used to reach the INSERT and die on the foreign key
with a bare 500 — the same class the unit refusal closed. The write
layer now refuses before the row is built, naming the field.

The update door carries none of the three columns — ShoppingListItemUpdate
has no item_id, category_id or template_id — so a PUT cannot set them and
needs no check. The suggestions door fills the columns from rows the
engine itself read, never from caller input.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models import Category, Item, ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.shopping_lists.models import ShoppingList
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


@pytest.fixture
def test_shopping_list(db_session: Session, test_user: Any) -> ShoppingList:
    shopping_list = ShoppingList(
        organization_id=test_user.organization_id,
        created_by=test_user.id,
        name='Reference refusal list',
    )
    db_session.add(shopping_list)
    db_session.commit()
    db_session.refresh(shopping_list)
    return shopping_list


@pytest.fixture
def real_category(db_session: Session, test_user: Any) -> Category:
    """A category of the caller's organization — the happy-path control."""
    category = Category(
        organization_id=test_user.organization_id,
        name=f'Produce {uuid4().hex[:6]}',
    )
    db_session.add(category)
    db_session.commit()
    db_session.refresh(category)
    return category


@pytest.fixture
def real_template(db_session: Session, test_user: Any) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=test_user.organization_id,
        name=f'Card {uuid4().hex[:6]}',
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


@pytest.fixture
def real_item(
    db_session: Session, test_user: Any, real_template: ProductTemplate
) -> Item:
    """A live product card, built the way the shelf helpers build one."""
    location = StorageLocation(
        organization_id=test_user.organization_id,
        created_by=test_user.id,
        name=f'Pantry {uuid4().hex[:6]}',
    )
    db_session.add(location)
    db_session.flush()
    item = Item(
        organization_id=test_user.organization_id,
        storage_location_id=location.id,
        template_id=real_template.id,
        name=f'Milk {uuid4().hex[:6]}',
        quantity=1,
    )
    db_session.add(item)
    anchor_pending_records(db_session)
    db_session.commit()
    db_session.refresh(item)
    return item


class TestAnUnknownReferenceIsRefusedNotA500:
    def test_post_with_unknown_category_id_is_a_named_refusal(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Mystery', 'quantity': 1, 'category_id': str(uuid4())},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert 'category_id' in response.text

    def test_post_with_unknown_item_id_is_a_named_refusal(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Mystery', 'quantity': 1, 'item_id': str(uuid4())},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert 'item_id' in response.text

    def test_post_with_unknown_template_id_is_a_named_refusal(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Mystery', 'quantity': 1, 'template_id': str(uuid4())},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert 'template_id' in response.text

    def test_bulk_with_one_unknown_reference_refuses_the_whole_batch(
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
                {'name': 'Bad', 'quantity': 1, 'template_id': str(uuid4())},
            ],
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert 'template_id' in response.text

        # The batch is answered, not the remainder after the first offender:
        # the good line must not have landed either.
        list_response = client.get(
            f'/api/v1/shopping-lists/{test_shopping_list.id}',
            headers=auth_headers,
        )
        assert list_response.status_code == status.HTTP_200_OK
        assert not list_response.json()['items']

    def test_real_references_still_land(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
        real_category: Category,
        real_item: Item,
        real_template: ProductTemplate,
    ) -> None:
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={
                'name': 'Flour',
                'quantity': 2,
                'category_id': str(real_category.id),
                'item_id': str(real_item.id),
                'template_id': str(real_template.id),
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        body = response.json()
        assert body['category_id'] == str(real_category.id)
        assert body['item_id'] == str(real_item.id)
        assert body['template_id'] == str(real_template.id)

    def test_explicit_null_references_still_land(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """A null is a clear, not an unknown key — the row must land."""

        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={
                'name': 'Bread',
                'quantity': 1,
                'category_id': None,
                'item_id': None,
                'template_id': None,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert response.json()['item_id'] is None

    async def test_the_cross_module_api_refuses_an_unknown_template(
        self,
        real_async_db_session: Any,
        async_test_user: Any,
    ) -> None:
        """The door the recipes module uses refuses the same way, as a rejection."""
        from app.core.contracts import ShoppingListItemCreateDTO
        from app.core.exceptions import ServiceRejectionError
        from app.modules.shopping_lists.shopping_lists_api import shopping_lists_api

        shopping_list = ShoppingList(
            organization_id=async_test_user.organization_id,
            created_by=async_test_user.id,
            name='API door',
        )
        real_async_db_session.add(shopping_list)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(shopping_list)

        unknown_template = uuid4()
        with pytest.raises(ServiceRejectionError) as exc_info:
            await shopping_lists_api.add_items_async(
                real_async_db_session,
                shopping_list.id,
                [
                    ShoppingListItemCreateDTO(
                        name='Mystery',
                        quantity=Decimal('1'),
                        template_id=unknown_template,
                    )
                ],
                async_test_user.organization_id,
            )
        assert str(unknown_template) in str(exc_info.value)

        # Nothing landed through the refused call.
        rows = await shopping_lists_api.get_list_items_async(
            real_async_db_session, shopping_list.id, async_test_user.organization_id
        )
        assert rows == []

    async def test_the_cross_module_api_takes_real_references(
        self,
        real_async_db_session: Any,
        async_test_user: Any,
    ) -> None:
        from app.core.contracts import ShoppingListItemCreateDTO
        from app.modules.shopping_lists.shopping_lists_api import shopping_lists_api

        shopping_list = ShoppingList(
            organization_id=async_test_user.organization_id,
            created_by=async_test_user.id,
            name='API door, good ids',
        )
        real_async_db_session.add(shopping_list)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(shopping_list)

        created = await shopping_lists_api.add_items_async(
            real_async_db_session,
            shopping_list.id,
            [ShoppingListItemCreateDTO(name='Bread', quantity=Decimal('1'))],
            async_test_user.organization_id,
        )
        assert [row.name for row in created] == ['Bread']
