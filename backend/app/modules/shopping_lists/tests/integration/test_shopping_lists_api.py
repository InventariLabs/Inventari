"""
Integration tests for shopping lists API endpoints.

Tests verify correctness of endpoints:
- POST /api/shopping-lists - create shopping list
- GET /api/shopping-lists - list shopping lists
- GET /api/shopping-lists/{list_id} - get shopping list details
- PUT /api/shopping-lists/{list_id} - update shopping list
- DELETE /api/shopping-lists/{list_id} - delete shopping list
- POST /api/shopping-lists/{list_id}/items - add item to list
- GET /api/shopping-lists/{list_id}/items - get list items
- PUT /api/shopping-lists/{list_id}/items/{item_id} - update list item
- PATCH /api/shopping-lists/{list_id}/items/{item_id}/purchase - mark as purchased
- PATCH /api/shopping-lists/{list_id}/items/{item_id}/unpurchase - unmark as purchased
- DELETE /api/shopping-lists/{list_id}/items/{item_id} - delete item from list
- DELETE /api/shopping-lists/{list_id}/items/purchased - clear purchased items
"""

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.user import User
from app.modules.shopping_lists.models import ShoppingList, ShoppingListItem


@pytest.mark.integration
class TestShoppingListsCreate:
    """Tests for shopping list creation endpoint."""

    def test_create_shopping_list_success(
        self, client: TestClient, auth_headers: dict[str, str], test_user: User
    ) -> None:
        """Tests successful shopping list creation."""
        response = client.post(
            '/api/v1/shopping-lists',
            headers=auth_headers,
            json={'name': 'Biedronka Shopping'},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'Biedronka Shopping'
        assert data['status'] == 'active'
        assert 'is_active' not in data
        assert 'id' in data
        assert data['organization_id'] == str(test_user.organization_id)

    def test_create_shopping_list_auto_generated_name(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Tests creating shopping list with auto-generated name based on date."""
        response = client.post('/api/v1/shopping-lists', headers=auth_headers, json={})

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        # Name should be in format "Shopping List DD Month" (e.g., "Shopping List 29 January")
        assert data['name'].startswith('Shopping List ')
        # Verify it contains a day number and month name
        import re

        assert re.match(r'Shopping List \d+ \w+', data['name'])

    def test_create_shopping_list_multiple_same_day(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        """Tests creating multiple shopping lists on the same day - should have incrementing suffix."""
        import re

        # Create first list with auto-generated name
        response1 = client.post('/api/v1/shopping-lists', headers=auth_headers, json={})
        assert response1.status_code == status.HTTP_201_CREATED
        name1 = response1.json()['name']

        # Create second list with custom name
        response2 = client.post(
            '/api/v1/shopping-lists', headers=auth_headers, json={'name': 'Custom list'}
        )
        assert response2.status_code == status.HTTP_201_CREATED
        name2 = response2.json()['name']
        assert name2 == 'Custom list'

        # Create third list with auto-generated name
        response3 = client.post('/api/v1/shopping-lists', headers=auth_headers, json={})
        assert response3.status_code == status.HTTP_201_CREATED
        name3 = response3.json()['name']

        # First auto-generated should not have suffix (no parentheses)
        assert '(' not in name1

        # Third auto-generated should have a suffix with number in parentheses
        # Format: "Shopping List 29 January (N)" where N >= 2
        match = re.search(r'\((\d+)\)$', name3)
        assert match is not None, f"Expected suffix like '(N)' in '{name3}'"
        suffix_number = int(match.group(1))
        assert suffix_number >= 2, f'Expected suffix number >= 2, got {suffix_number}'

    def test_create_shopping_list_no_household(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        auth_headers: dict[str, str],
    ) -> None:
        """Tests creating shopping list without organization assignment."""

        test_user.organization_id = None
        db_session.commit()

        response = client.post(
            '/api/v1/shopping-lists', headers=auth_headers, json={'name': 'Test'}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        detail = response.json()['detail']
        assert detail['code'] == 'MODULES_NO_ORGANIZATION'
        assert 'organization' in detail['message'].lower()

    def test_create_shopping_list_unauthorized(self, client: TestClient) -> None:
        """Tests creating shopping list without authorization."""
        response = client.post('/api/v1/shopping-lists', json={'name': 'Test'})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestShoppingListsList:
    """Tests for shopping lists list endpoint."""

    def test_get_shopping_lists_empty(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Tests fetching empty shopping lists."""
        response = client.get('/api/v1/shopping-lists', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['items'] == []

    def test_get_shopping_lists_no_household(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        auth_headers: dict[str, str],
    ) -> None:
        """Tests fetching shopping lists without organization assignment."""

        test_user.organization_id = None
        db_session.commit()

        response = client.get('/api/v1/shopping-lists', headers=auth_headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        detail = response.json()['detail']
        assert detail['code'] == 'MODULES_NO_ORGANIZATION'
        assert 'organization' in detail['message'].lower()

    def test_get_shopping_lists_with_data(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """Tests fetching shopping lists with data."""
        response = client.get('/api/v1/shopping-lists', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        lists = response.json()['items']
        assert len(lists) >= 1
        assert any(lst['id'] == str(test_shopping_list.id) for lst in lists)

    def test_get_shopping_lists_active_only(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
        db_session: Session,
    ) -> None:
        """Tests fetching only lists that have not left the screens."""
        test_shopping_list.status = 'archived'
        db_session.commit()

        response = client.get(
            '/api/v1/shopping-lists?active_only=true', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        lists = response.json()['items']
        # The deactivated list should not appear
        assert not any(lst['id'] == str(test_shopping_list.id) for lst in lists)

    def test_get_shopping_lists_unauthorized(self, client: TestClient) -> None:
        """Tests fetching shopping lists without authorization."""
        response = client.get('/api/v1/shopping-lists')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestShoppingListDetails:
    """Tests for shopping list details endpoint."""

    def test_get_shopping_list_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """Tests successful shopping list details fetching."""
        response = client.get(
            f'/api/v1/shopping-lists/{test_shopping_list.id}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['id'] == str(test_shopping_list.id)
        assert data['name'] == test_shopping_list.name

    def test_get_shopping_list_not_found(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Tests fetching non-existent shopping list."""
        response = client.get(f'/api/v1/shopping-lists/{uuid4()}', headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_shopping_list_unauthorized(
        self, client: TestClient, test_shopping_list: ShoppingList
    ) -> None:
        """Tests fetching shopping list details without authorization."""
        response = client.get(f'/api/v1/shopping-lists/{test_shopping_list.id}')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestShoppingListUpdate:
    """Tests for shopping list update endpoint."""

    def test_update_shopping_list_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """Tests successful shopping list update."""
        response = client.put(
            f'/api/v1/shopping-lists/{test_shopping_list.id}',
            headers=auth_headers,
            json={'name': 'Updated list', 'status': 'completed'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['name'] == 'Updated list'
        assert data['status'] == 'completed'

    def test_update_shopping_list_not_found(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Tests updating non-existent shopping list."""
        response = client.put(
            f'/api/v1/shopping-lists/{uuid4()}',
            headers=auth_headers,
            json={'name': 'New name'},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestShoppingListDelete:
    """Tests for shopping list deletion endpoint."""

    def test_delete_shopping_list_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        """Tests successful shopping list deletion."""
        from app.modules.shopping_lists.models import ShoppingList

        shopping_list = ShoppingList(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='To delete',
        )
        db_session.add(shopping_list)
        db_session.commit()

        response = client.delete(
            f'/api/v1/shopping-lists/{shopping_list.id}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_shopping_list_not_found(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Tests deleting non-existent shopping list."""
        response = client.delete(
            f'/api/v1/shopping-lists/{uuid4()}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestShoppingListItems:
    """Tests for shopping list items endpoints."""

    def test_add_item_to_list_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """Tests successful adding item to shopping list."""
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={
                'name': 'Milk',
                'quantity': 2,
                'notes': 'Full fat 3.2%',
                'priority': 1,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'Milk'
        assert Decimal(str(data['quantity'])) == 2
        assert data['is_purchased'] == False
        assert data['source'] == 'manual'

    def test_a_fraction_the_store_holds_lands_on_the_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """Half a kilogram of flour is a legitimate line: the column holds
        three decimals, and the form that blocks a fraction is the only
        place a person types a quantity in. The API answers for the store
        here — half a unit goes in as half."""
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Flour', 'quantity': 0.5},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert Decimal(str(data['quantity'])) == Decimal('0.5')

    def test_a_quantity_the_column_cannot_hold_is_a_sentence_not_a_500(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """numeric(12, 3) overflows on a twelve-digit quantity, and the
        overflow used to surface as a bare 500 from the driver. The schema
        knows the column's ceiling and refuses above it with the same kind
        of sentence every other quantity refusal gets."""
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Unobtainium', 'quantity': 1000000000},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        # The schema names the ceiling the column holds — the same number
        # the form repeats before the request even leaves.
        assert '999999999.999' in response.text

        # The update path quantizes through the same schema, so the same
        # quantity dies there too instead of at the driver.
        item = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Flour', 'quantity': 1},
        )
        update = client.put(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items/{item.json()["id"]}',
            headers=auth_headers,
            json={'quantity': 1000000000},
        )
        assert update.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert '999999999.999' in update.text

    def test_add_item_to_list_not_found(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Tests adding item to non-existent shopping list."""
        response = client.post(
            f'/api/v1/shopping-lists/{uuid4()}/items',
            headers=auth_headers,
            json={'name': 'Test'},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_list_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list_item: ShoppingListItem,
    ) -> None:
        """Tests fetching items from shopping list."""
        response = client.get(
            f'/api/v1/shopping-lists/{test_shopping_list_item.shopping_list_id}/items',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()
        assert len(items) >= 1

    def test_update_list_item(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list_item: ShoppingListItem,
    ) -> None:
        """Tests updating shopping list item."""
        response = client.put(
            f'/api/v1/shopping-lists/{test_shopping_list_item.shopping_list_id}/items/{test_shopping_list_item.id}',
            headers=auth_headers,
            json={'quantity': 5, 'notes': 'Updated note'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert Decimal(str(data['quantity'])) == 5
        assert data['notes'] == 'Updated note'


@pytest.mark.integration
class TestShoppingListItemPurchase:
    """Tests for marking items as purchased/unpurchased."""

    def test_mark_item_as_purchased(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list_item: ShoppingListItem,
    ) -> None:
        """Tests marking item as purchased."""
        response = client.patch(
            f'/api/v1/shopping-lists/{test_shopping_list_item.shopping_list_id}/items/{test_shopping_list_item.id}/purchase',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['is_purchased'] == True
        assert data['purchased_at'] is not None

    def test_mark_missing_item_as_purchased_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """Missing item purchase should return 404, not leak a stale update error."""
        response = client.patch(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items/{uuid4()}/purchase',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_mark_item_deleted_after_purchase_update_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_shopping_list_item: ShoppingListItem,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Concurrent delete after the update should return 404, not refresh a stale row."""
        from sqlalchemy import delete
        from sqlalchemy.orm import sessionmaker

        original_commit = db_session.commit
        deleted = False

        def commit_then_delete_item() -> None:
            nonlocal deleted
            original_commit()
            if deleted:
                return
            deleted = True
            session_local = sessionmaker(bind=db_session.get_bind())
            cleanup_session = session_local()
            try:
                cleanup_session.execute(
                    delete(ShoppingListItem).where(
                        ShoppingListItem.id == test_shopping_list_item.id
                    )
                )
                cleanup_session.commit()
            finally:
                cleanup_session.close()

        monkeypatch.setattr(db_session, 'commit', commit_then_delete_item)

        response = client.patch(
            f'/api/v1/shopping-lists/{test_shopping_list_item.shopping_list_id}/items/{test_shopping_list_item.id}/purchase',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_mark_item_as_unpurchased(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list_item: ShoppingListItem,
    ) -> None:
        """Tests unmarking item as purchased."""
        # First mark as purchased
        client.patch(
            f'/api/v1/shopping-lists/{test_shopping_list_item.shopping_list_id}/items/{test_shopping_list_item.id}/purchase',
            headers=auth_headers,
        )

        # Then unmark
        response = client.patch(
            f'/api/v1/shopping-lists/{test_shopping_list_item.shopping_list_id}/items/{test_shopping_list_item.id}/unpurchase',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['is_purchased'] == False
        assert data['purchased_at'] is None

    def test_mark_missing_item_as_unpurchased_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """Missing item unpurchase should return 404, not leak a stale update error."""
        response = client.patch(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items/{uuid4()}/unpurchase',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestShoppingListItemDelete:
    """Tests for deleting items from shopping list."""

    def test_delete_item_from_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_shopping_list: ShoppingList,
    ) -> None:
        """Tests deleting item from shopping list."""
        from app.modules.shopping_lists.models import ShoppingListItem

        item = ShoppingListItem(
            shopping_list_id=test_shopping_list.id, name='To be deleted', quantity=1
        )
        db_session.add(item)
        db_session.commit()

        response = client.delete(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items/{item.id}',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_clear_purchased_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_shopping_list: ShoppingList,
    ) -> None:
        """Tests clearing all purchased items from list."""
        from app.modules.shopping_lists.models import ShoppingListItem

        # Create purchased item
        purchased_item = ShoppingListItem(
            shopping_list_id=test_shopping_list.id,
            name='Purchased item',
            quantity=1,
            is_purchased=True,
        )
        db_session.add(purchased_item)
        db_session.commit()

        response = client.delete(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items/purchased',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT


# Fixtures for shopping list tests
@pytest.fixture
def test_shopping_list(db_session: Session, test_user: User) -> ShoppingList:
    """Creates test shopping list."""
    from app.modules.shopping_lists.models import ShoppingList

    shopping_list = ShoppingList(
        organization_id=test_user.organization_id,
        created_by=test_user.id,
        name='Test shopping list',
    )
    db_session.add(shopping_list)
    db_session.commit()
    db_session.refresh(shopping_list)
    return shopping_list


@pytest.fixture
def test_shopping_list_item(
    db_session: Session,
    test_shopping_list: ShoppingList,
    test_category: Any,
    test_user: User,
) -> ShoppingListItem:
    """Creates test shopping list item."""
    from app.modules.shopping_lists.models import ShoppingListItem

    item = ShoppingListItem(
        shopping_list_id=test_shopping_list.id,
        name='Test product',
        quantity=2,
        category_id=test_category.id,
        priority=0,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


# === AUTO-SUGGESTIONS TESTS ===


@pytest.mark.integration
class TestShoppingListSuggestions:
    """Tests for auto-suggestions endpoints."""

    def test_generate_suggestions_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """Tests successful suggestions generation."""
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/suggestions/generate',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'message' in data
        assert 'added' in data
        assert 'suggestions' in data
        assert isinstance(data['suggestions'], list)

    def test_generate_suggestions_not_found(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Tests generating suggestions for non-existent list."""
        response = client.post(
            f'/api/v1/shopping-lists/{uuid4()}/suggestions/generate',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_generate_suggestions_unauthorized(
        self, client: TestClient, test_shopping_list: ShoppingList
    ) -> None:
        """Tests generating suggestions without authorization."""
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/suggestions/generate'
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_add_all_suggestions_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
        db_session: Session,
        test_item: Any,
    ) -> None:
        """Tests successfully adding all suggestions to list."""
        # test_item has quantity=2, we need to set it to 1 for low stock suggestion
        test_item.quantity = 1
        db_session.commit()

        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/suggestions/add-all',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'message' in data
        assert 'added' in data
        assert 'suggestions' in data

    def test_add_all_suggestions_not_found(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Tests adding suggestions for non-existent list."""
        response = client.post(
            f'/api/v1/shopping-lists/{uuid4()}/suggestions/add-all',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_add_all_suggestions_unauthorized(
        self, client: TestClient, test_shopping_list: ShoppingList
    ) -> None:
        """Tests adding suggestions without authorization."""
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/suggestions/add-all'
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestTheDoorQuantisesAndRefusesTheZero:
    def test_a_create_quantizes_to_the_store_precision(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Flour', 'quantity': 1.23456},
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        # The echo is the number the store keeps — not the number that was
        # sent, which the column would have rounded behind the reply's back.
        assert response.json()['quantity'] == '1.235'

    def test_an_update_quantizes_to_the_store_precision(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        item_id = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Flour', 'quantity': 1},
        ).json()['id']

        response = client.put(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items/{item_id}',
            headers=auth_headers,
            json={'quantity': 2.99949},
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['quantity'] == '2.999'

    def test_a_quantity_that_rounds_to_zero_is_refused_at_the_door(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """0.0004 would be stored as 0.000, which the read schema refuses —
        bricking every later read of the list. The write is refused instead,
        in the reader's language."""
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Saffron', 'quantity': 0.0004},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'SHOPPING_LIST_ITEM_QUANTITY_ROUNDS_TO_ZERO'
        assert 'zero' in detail['message'].lower()
        assert detail['message'] != detail['message'].lower()  # a sentence, not a key

    def test_the_rounding_zero_refusal_speaks_the_interface_language(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """The sentence is written for the reader, so it arrives in the
        language the request asked for — the form's toast reads this
        `detail`, and an English answer under a Polish interface is how a
        refusal stops being readable."""
        response = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers={**auth_headers, 'Accept-Language': 'pl'},
            json={'name': 'Saffron', 'quantity': 0.0004},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        detail = response.json()['detail']['message']
        code = response.json()['detail']['code']
        assert code == 'SHOPPING_LIST_ITEM_QUANTITY_ROUNDS_TO_ZERO'
        assert 'najmniejsza zapisywalna ilość' in detail
        assert 'countable' not in detail

    def test_an_update_to_a_rounding_zero_is_refused(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        item_id = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Flour', 'quantity': 1},
        ).json()['id']

        response = client.put(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items/{item_id}',
            headers=auth_headers,
            json={'quantity': 0.0004},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text

    def test_the_list_still_reads_after_the_refusals(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_shopping_list: ShoppingList,
    ) -> None:
        """A regression: one saved zero made every later GET of the
        list a 500. Nothing below the floor may reach the store — so the
        test tries to save one, both through a new line and through an
        update, and only then reads the list."""
        item_id = client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Flour', 'quantity': 1},
        ).json()['id']
        client.post(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items',
            headers=auth_headers,
            json={'name': 'Saffron', 'quantity': 0.0004},
        )
        client.put(
            f'/api/v1/shopping-lists/{test_shopping_list.id}/items/{item_id}',
            headers=auth_headers,
            json={'quantity': 0.0004},
        )

        response = client.get(
            f'/api/v1/shopping-lists/{test_shopping_list.id}',
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK, response.text
