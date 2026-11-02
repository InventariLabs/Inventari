"""
Integration tests for recursive stock takes with full tree locks.

A stock take of a parent location must snapshot items from the location
and all its descendants, and an active stock take anywhere in the tree
must block a new stock take anywhere else in the tree.
"""

from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User


def _create_location(
    db_session: Session,
    org_id: UUID,
    user_id: UUID,
    storage_type_id: UUID,
    name: str,
    parent_id: UUID | None = None,
) -> StorageLocation:
    location = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        storage_type_id=storage_type_id,
        name=name,
        parent_id=parent_id,
    )
    db_session.add(location)
    db_session.commit()
    db_session.refresh(location)
    return location


def _create_item(
    db_session: Session,
    location: StorageLocation,
    category: Category,
    name: str,
    quantity: float,
) -> Item:
    item = Item(
        organization_id=location.organization_id,
        storage_location_id=location.id,
        category_id=category.id,
        name=name,
        quantity=quantity,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.mark.integration
class TestRecursiveStockTake:
    def test_parent_stock_take_includes_descendant_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_type: StorageType,
        test_category: Category,
    ) -> None:
        """Items in child locations must be part of the parent stock take."""
        assert test_user.organization_id is not None
        parent = _create_location(
            db_session,
            test_user.organization_id,
            test_user.id,
            test_storage_type.id,
            'Rack A',
        )
        child = _create_location(
            db_session,
            test_user.organization_id,
            test_user.id,
            test_storage_type.id,
            'Shelf 1',
            parent_id=parent.id,
        )
        _create_item(db_session, parent, test_category, 'Top item', 3)
        _create_item(db_session, child, test_category, 'Shelf item', 7)

        response = client.post(
            '/api/v1/stock-takes',
            headers=auth_headers,
            json={
                'name': 'Recursive stock take',
                'location_id': str(parent.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['items_count'] == 2

        items_response = client.get(
            f'/api/v1/stock-takes/{data["id"]}/items', headers=auth_headers
        )
        assert items_response.status_code == status.HTTP_200_OK
        item_names = {item['item_name'] for item in items_response.json()['items']}
        assert item_names == {'Top item', 'Shelf item'}

    def test_active_stock_take_blocks_sibling_subtree(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_type: StorageType,
        test_category: Category,
    ) -> None:
        """An active stock take on the parent blocks a child stock take."""
        assert test_user.organization_id is not None
        parent = _create_location(
            db_session,
            test_user.organization_id,
            test_user.id,
            test_storage_type.id,
            'Rack B',
        )
        child = _create_location(
            db_session,
            test_user.organization_id,
            test_user.id,
            test_storage_type.id,
            'Shelf 2',
            parent_id=parent.id,
        )
        _create_item(db_session, parent, test_category, 'Parent item', 1)
        _create_item(db_session, child, test_category, 'Child item', 2)

        parent_response = client.post(
            '/api/v1/stock-takes',
            headers=auth_headers,
            json={
                'name': 'Parent stock take',
                'location_id': str(parent.id),
            },
        )
        assert parent_response.status_code == status.HTTP_201_CREATED

        child_response = client.post(
            '/api/v1/stock-takes',
            headers=auth_headers,
            json={
                'name': 'Child stock take',
                'location_id': str(child.id),
            },
        )

        assert child_response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            'active stock take already exists'
            in child_response.json()['detail']['message']
        )
