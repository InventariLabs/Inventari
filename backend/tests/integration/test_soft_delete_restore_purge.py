from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy import select

from app.services.token_service import create_access_token


def _auth(user):
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.integration
class TestSoftDelete:
    def test_soft_delete_sets_is_deleted_true(
        self, client, auth_headers, db_session, test_item
    ):
        """A delete that named no reason keeps none.

        Both reason-less doors in the interface — the bulk delete behind one
        confirmation and the swipe on the mobile card — send no body at all,
        so this request is what they look like on the wire. It used to come
        back filed as ``OTHER``, and the archived sheet read that out loud as
        "Status: Other": an answer nobody gave, said with confidence.
        """
        response = client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)

        assert response.status_code == status.HTTP_204_NO_CONTENT

        db_session.refresh(test_item)
        assert test_item.is_deleted is True
        assert test_item.deleted_at is not None
        assert test_item.deleted_by is not None
        assert test_item.deletion_reason is None
        assert test_item.quantity == 0

    def test_soft_delete_with_a_body_but_no_reason_keeps_none(
        self, client, auth_headers, db_session, test_item
    ):
        """A body that names only notes is not a reason either.

        The schema used to default the field to ``OTHER``, so a caller that
        arrived with something to say about the delete but nothing about the
        why had the why invented for them.
        """
        response = client.request(
            'DELETE',
            f'/api/v1/items/{test_item.id}',
            headers=auth_headers,
            json={'notes': 'cleaned up the shelf'},
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        db_session.refresh(test_item)
        assert test_item.deletion_reason is None

    def test_soft_delete_with_reason(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        from app.models.item import Item as ItemModel

        item = ItemModel(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='To delete with reason',
            quantity=3,
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        response = client.request(
            'DELETE',
            f'/api/v1/items/{item.id}',
            headers=auth_headers,
            json={'reason': 'TEST_DATA', 'notes': 'Cleanup'},
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        db_session.refresh(item)
        assert item.is_deleted is True
        assert item.deletion_reason == 'TEST_DATA'

    def test_soft_delete_removes_from_items_list(
        self, client, auth_headers, db_session, test_item
    ):
        client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)

        response = client.get('/api/v1/items', headers=auth_headers)
        data = response.json()
        assert not any(i['id'] == str(test_item.id) for i in data['items'])

    def test_soft_delete_shows_in_archived(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        from app.models.item import Item as ItemModel

        item = ItemModel(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='To archive',
            quantity=1,
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        client.request(
            'DELETE',
            f'/api/v1/items/{item.id}',
            headers=auth_headers,
            json={'reason': 'DAMAGED'},
        )

        response = client.get('/api/v1/items/archived', headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        assert any(i['id'] == str(item.id) for i in data)
        archived = next(i for i in data if i['id'] == str(item.id))
        assert archived['is_deleted'] is True
        assert archived['deletion_reason'] == 'DAMAGED'

    def test_archive_list_carries_the_note_given_when_deleting(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        """The delete dialog asks for a note; the archive, where the next
        decision (restore or purge) is made, has to show it. A product
        deleted twice shows the note of its latest deletion, and one deleted
        without a note shows none."""
        from app.models.item import Item as ItemModel

        def make(name):
            item = ItemModel(
                organization_id=test_user.organization_id,
                storage_location_id=test_storage_location.id,
                category_id=test_category.id,
                name=name,
                quantity=1,
            )
            db_session.add(item)
            db_session.commit()
            db_session.refresh(item)
            return item

        noted = make('Deleted with a note')
        plain = make('Deleted without a note')
        twice = make('Deleted twice')

        def delete(item, body):
            r = client.request(
                'DELETE', f'/api/v1/items/{item.id}', headers=auth_headers, json=body
            )
            assert r.status_code == status.HTTP_204_NO_CONTENT

        delete(noted, {'reason': 'TEST_DATA', 'notes': 'wrong product'})
        delete(plain, {'reason': 'TEST_DATA'})
        delete(twice, {'reason': 'LOST', 'notes': 'first time'})
        r = client.post(f'/api/v1/items/{twice.id}/restore', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK, r.text
        delete(twice, {'reason': 'LOST', 'notes': 'second time'})

        rows = {
            i['id']: i
            for i in client.get('/api/v1/items/archived', headers=auth_headers).json()[
                'items'
            ]
        }
        assert rows[str(noted.id)]['deletion_notes'] == 'wrong product'
        assert rows[str(plain.id)]['deletion_notes'] is None
        assert rows[str(twice.id)]['deletion_notes'] == 'second time'

    def test_soft_delete_double_delete_returns_error(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        from app.models.item import Item as ItemModel

        item = ItemModel(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='Double delete',
            quantity=1,
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        client.delete(f'/api/v1/items/{item.id}', headers=auth_headers)

        response = client.delete(f'/api/v1/items/{item.id}', headers=auth_headers)
        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    def test_soft_delete_logs_history(
        self, client, auth_headers, db_session, test_item
    ):
        client.request(
            'DELETE',
            f'/api/v1/items/{test_item.id}',
            headers=auth_headers,
            json={'reason': 'LOST'},
        )

        from app.models.item_history import ItemHistory

        history = list(
            db_session.scalars(
                select(ItemHistory).where(ItemHistory.item_id == test_item.id)
            ).all()
        )
        assert any(h.action == 'DELETED' for h in history)


@pytest.mark.integration
class TestRestoreItem:
    def test_restore_sets_is_deleted_false(
        self, client, auth_headers, db_session, test_item
    ):
        client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)

        response = client.post(
            f'/api/v1/items/{test_item.id}/restore', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['is_deleted'] is False
        assert data['deleted_at'] is None
        assert data['deletion_reason'] is None

        db_session.refresh(test_item)
        assert test_item.is_deleted is False

    def test_restore_preserves_original_quantity(
        self, client, auth_headers, db_session, test_item
    ):
        """restore_item must restore the original quantity, not hardcode 1.

        Bug: _lifecycle.py:114 was apply_quantity_change(db, item, Decimal('1')),
        losing the pre-deletion quantity. delete_item stores old_quantity in
        the DELETED history entry; restore should read it back.
        """
        original_qty = test_item.quantity

        client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)

        response = client.post(
            f'/api/v1/items/{test_item.id}/restore', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert Decimal(data['quantity']) == original_qty, (
            f'Expected {original_qty} after restore, got {data["quantity"]}'
        )

    def test_restore_returns_item_to_list(
        self, client, auth_headers, db_session, test_item
    ):
        client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)
        client.post(f'/api/v1/items/{test_item.id}/restore', headers=auth_headers)

        response = client.get('/api/v1/items', headers=auth_headers)
        data = response.json()
        assert any(i['id'] == str(test_item.id) for i in data['items'])

    def test_restore_non_deleted_returns_error(self, client, auth_headers, test_item):
        response = client.post(
            f'/api/v1/items/{test_item.id}/restore', headers=auth_headers
        )

        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    def test_restore_nonexistent_returns_404(self, client, auth_headers):
        response = client.post(f'/api/v1/items/{uuid4()}/restore', headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_restore_logs_history(
        self, real_async_client, real_async_db_session, async_test_user, async_test_item
    ):
        db = real_async_db_session
        await db.commit()  # commit async_test_user + async_test_item
        headers = _auth(async_test_user)

        await real_async_client.delete(
            f'/api/v1/items/{async_test_item.id}', headers=headers
        )
        await real_async_client.post(
            f'/api/v1/items/{async_test_item.id}/restore', headers=headers
        )

        from app.models.item_history import ItemHistory

        result = await db.execute(
            select(ItemHistory).where(ItemHistory.item_id == async_test_item.id)
        )
        history = list(result.scalars().all())
        assert any(h.action == 'RESTORED' for h in history)


@pytest.mark.integration
class TestPurgeItem:
    @pytest.mark.asyncio
    async def test_purge_removes_from_db(
        self, real_async_client, real_async_db_session, async_test_user, async_test_item
    ):
        db = real_async_db_session
        await db.commit()  # commit async_test_user + async_test_item
        headers = _auth(async_test_user)
        item_id = async_test_item.id

        await real_async_client.delete(f'/api/v1/items/{item_id}', headers=headers)

        response = await real_async_client.delete(
            f'/api/v1/items/{item_id}/purge', headers=headers
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        from app.models.item import Item

        result = await db.execute(select(Item).where(Item.id == item_id))
        item = result.scalars().first()
        assert item is None

    def test_purge_active_item_returns_error(self, client, auth_headers, test_item):
        response = client.delete(
            f'/api/v1/items/{test_item.id}/purge', headers=auth_headers
        )

        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    def test_purge_nonexistent_returns_404(self, client, auth_headers):
        response = client.delete(f'/api/v1/items/{uuid4()}/purge', headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_purge_removes_from_archived(
        self, client, auth_headers, db_session, test_item
    ):
        client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)
        client.delete(f'/api/v1/items/{test_item.id}/purge', headers=auth_headers)

        response = client.get('/api/v1/items/archived', headers=auth_headers)
        data = response.json()['items']
        assert not any(i['id'] == str(test_item.id) for i in data)


@pytest.mark.integration
class TestArchivedPagination:
    def _archive_items(
        self,
        client,
        auth_headers,
        db_session,
        test_user,
        test_storage_location,
        count,
    ):
        from datetime import datetime

        from app.models.item import Item as ItemModel

        items = []
        for i in range(count):
            item = ItemModel(
                organization_id=test_user.organization_id,
                storage_location_id=test_storage_location.id,
                category_id=None,
                name=f'Archived {i}',
                quantity=0,
                is_deleted=True,
                deleted_at=datetime(2026, 7, 20 + i),
            )
            db_session.add(item)
            items.append(item)
        db_session.commit()
        return items

    def test_archived_items_pagination_envelope(
        self,
        client,
        auth_headers,
        db_session,
        test_user,
        test_storage_location,
    ):
        self._archive_items(
            client, auth_headers, db_session, test_user, test_storage_location, 5
        )

        response = client.get(
            '/api/v1/items/archived?limit=2&offset=0', headers=auth_headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['total'] == 5
        assert data['limit'] == 2
        assert data['offset'] == 0
        assert data['has_more'] is True
        assert len(data['items']) == 2

    def test_archived_items_pagination_last_page(
        self,
        client,
        auth_headers,
        db_session,
        test_user,
        test_storage_location,
    ):
        self._archive_items(
            client, auth_headers, db_session, test_user, test_storage_location, 5
        )

        response = client.get(
            '/api/v1/items/archived?limit=2&offset=4', headers=auth_headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['total'] == 5
        assert data['has_more'] is False
        assert len(data['items']) == 1

    def test_archived_items_pagination_pages_are_distinct(
        self,
        client,
        auth_headers,
        db_session,
        test_user,
        test_storage_location,
    ):
        self._archive_items(
            client, auth_headers, db_session, test_user, test_storage_location, 5
        )

        page1 = client.get(
            '/api/v1/items/archived?limit=2&offset=0', headers=auth_headers
        ).json()['items']
        page2 = client.get(
            '/api/v1/items/archived?limit=2&offset=2', headers=auth_headers
        ).json()['items']

        ids1 = {i['id'] for i in page1}
        ids2 = {i['id'] for i in page2}
        assert len(ids1) == 2
        assert len(ids2) == 2
        assert ids1.isdisjoint(ids2)
