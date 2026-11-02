"""
Integration tests for storages API endpoints.

Tests verify correctness of endpoints:
- GET /api/v1/locations - list storage locations
- GET /api/v1/locations/tree - hierarchical tree
- POST /api/v1/locations - create storage location
- GET /api/v1/locations/{location_id} - storage location details
- GET /api/v1/locations/{location_id}/breadcrumb - ancestor path
- PUT /api/v1/locations/{location_id} - update storage location
- DELETE /api/v1/locations/{location_id} - delete storage location
- GET /api/v1/locations/{location_id}/summary - storage location summary
- GET /api/v1/locations/{location_id}/items - items in storage location
- GET /api/v1/locations/{location_id}/print - storage label printing
"""

import pytest
from fastapi import status


@pytest.mark.integration
class TestStoragesList:
    """Tests for storage locations list endpoint."""

    def test_get_storages_empty(self, client, auth_headers):
        """Tests fetching empty storage locations list."""
        response = client.get('/api/v1/locations', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['items'] == []

    def test_get_storages_with_data(self, client, auth_headers, test_storage_location):
        """Tests fetching storage locations list with data."""
        response = client.get('/api/v1/locations', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        storages = response.json()['items']
        assert len(storages) >= 1
        assert any(s['id'] == str(test_storage_location.id) for s in storages)

    def test_get_storages_unauthorized(self, client):
        """Tests fetching list without authorization."""
        response = client.get('/api/v1/locations')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_storages_usage_all_includes_virtual(
        self, client, auth_headers, db_session, test_user, test_storage_type
    ):
        """usage=all reaches the virtual counterparts the internal default hides."""
        from app.models.storage_location import LocationUsage, StorageLocation

        virtual = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='Consumed (Virtual)',
            usage=LocationUsage.CUSTOMER,
        )
        db_session.add(virtual)
        db_session.commit()

        default_ids = [
            s['id']
            for s in client.get('/api/v1/locations', headers=auth_headers).json()[
                'items'
            ]
        ]
        all_ids = [
            s['id']
            for s in client.get(
                '/api/v1/locations', params={'usage': 'all'}, headers=auth_headers
            ).json()['items']
        ]

        assert str(virtual.id) not in default_ids
        assert str(virtual.id) in all_ids


@pytest.mark.integration
class TestStoragesCreate:
    """Tests for storage location creation endpoint."""

    def test_create_storage_success(self, client, auth_headers, test_storage_type):
        """Tests successful storage location creation."""
        response = client.post(
            '/api/v1/locations',
            headers=auth_headers,
            json={
                'name': 'New freezer',
                'description': 'Additional freezer',
                'location_type_id': str(test_storage_type.id),
                'location_details': 'Basement',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'New freezer'
        assert data['description'] == 'Additional freezer'
        assert data['location_details'] == 'Basement'
        assert 'id' in data
        assert data['short_code'].startswith('LOC-')

    def test_create_storage_custom_prefix(
        self, client, auth_headers, test_storage_type
    ):
        """Tests storage creation with custom prefix."""
        response = client.post(
            '/api/v1/locations',
            headers=auth_headers,
            json={
                'name': 'Custom Prefix Storage',
                'location_type_id': str(test_storage_type.id),
                'short_code_prefix': 'PRE',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['short_code'].startswith('PRE-')

    def test_create_storage_minimal(self, client, auth_headers, test_storage_type):
        """Tests creating storage location with minimal data."""
        response = client.post(
            '/api/v1/locations',
            headers=auth_headers,
            json={
                'name': 'Minimal storage',
                'location_type_id': str(test_storage_type.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'Minimal storage'

    def test_create_storage_invalid_type(self, client, auth_headers):
        """Tests creating location with invalid type."""
        from uuid import uuid4

        response = client.post(
            '/api/v1/locations',
            headers=auth_headers,
            json={'name': 'Storage', 'location_type_id': str(uuid4())},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_storage_unauthorized(self, client, test_storage_type):
        """Tests creating location without authorization."""
        response = client.post(
            '/api/v1/locations',
            json={'name': 'Storage', 'location_type_id': str(test_storage_type.id)},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestStorageDetails:
    """Tests for storage location details endpoint."""

    def test_get_storage_success(self, client, auth_headers, test_storage_location):
        """Tests successful storage location details fetching."""
        response = client.get(
            f'/api/v1/locations/{test_storage_location.id}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['id'] == str(test_storage_location.id)
        assert data['name'] == test_storage_location.name

    def test_get_storage_not_found(self, client, auth_headers):
        """Tests fetching non-existent storage location."""
        from uuid import uuid4

        response = client.get(f'/api/v1/locations/{uuid4()}', headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_storage_unauthorized(self, client, test_storage_location):
        """Tests fetching details without authorization."""
        response = client.get(f'/api/v1/locations/{test_storage_location.id}')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestStorageUpdate:
    """Tests for storage location update endpoint."""

    def test_update_storage_success(self, client, auth_headers, test_storage_location):
        """Tests successful storage location update."""
        response = client.put(
            f'/api/v1/locations/{test_storage_location.id}',
            headers=auth_headers,
            json={'name': 'Updated name', 'description': 'Updated description'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['name'] == 'Updated name'
        assert data['description'] == 'Updated description'

    def test_update_storage_partial(self, client, auth_headers, test_storage_location):
        """Tests partial storage location update."""
        response = client.put(
            f'/api/v1/locations/{test_storage_location.id}',
            headers=auth_headers,
            json={'name': 'New name'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['name'] == 'New name'
        assert data['description'] == test_storage_location.description  # unchanged

    def test_the_ordering_number_is_set_listed_and_cleared(
        self, client, auth_headers, test_storage_location
    ):
        """A location's ordering number is the walk's: the list and the tree carry it."""
        url = f'/api/v1/locations/{test_storage_location.id}'
        response = client.put(url, headers=auth_headers, json={'sequence': 20})
        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['sequence'] == 20

        listed = client.get('/api/v1/locations', headers=auth_headers).json()['items']
        row = next(s for s in listed if s['id'] == str(test_storage_location.id))
        assert row['sequence'] == 20
        tree = client.get('/api/v1/locations/tree', headers=auth_headers).json()
        node = next(n for n in tree if n['id'] == str(test_storage_location.id))
        assert node['sequence'] == 20

        response = client.put(url, headers=auth_headers, json={'sequence': None})
        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['sequence'] is None

    def test_a_negative_ordering_number_is_refused(
        self, client, auth_headers, test_storage_location
    ):
        response = client.put(
            f'/api/v1/locations/{test_storage_location.id}',
            headers=auth_headers,
            json={'sequence': -1},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_update_storage_not_found(self, client, auth_headers):
        """Tests updating non-existent storage location."""
        from uuid import uuid4

        response = client.put(
            f'/api/v1/locations/{uuid4()}',
            headers=auth_headers,
            json={'name': 'New name'},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestStorageDelete:
    """Tests for storage location deletion endpoint."""

    def _create_location(self, client, auth_headers, name: str, parent_id=None) -> dict:
        payload = {'name': name}
        if parent_id is not None:
            payload['parent_id'] = parent_id
        response = client.post('/api/v1/locations', headers=auth_headers, json=payload)
        assert response.status_code == status.HTTP_201_CREATED, response.text
        return response.json()

    def _rows(self, client, auth_headers) -> dict:
        response = client.get('/api/v1/locations', headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK, response.text
        return {row['name']: row for row in response.json()['items']}

    def test_the_children_move_up_one_level_not_to_the_root(self, client, auth_headers):
        """Every confirmation in the application promises the child locations
        move up a level. The FK's ON DELETE SET NULL alone would drop them at
        the root instead — for a location three levels deep, a jump the
        reader was never told about. The grandchild keeps the parent that
        moved; only the direct children are lifted."""
        site = self._create_location(client, auth_headers, 'Site')
        zone = self._create_location(client, auth_headers, 'Zone', site['id'])
        shelf = self._create_location(client, auth_headers, 'Shelf', zone['id'])
        self._create_location(client, auth_headers, 'Shelf bin', shelf['id'])

        response = client.delete(
            f'/api/v1/locations/{zone["id"]}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        rows = self._rows(client, auth_headers)
        assert rows['Shelf']['parent_id'] == site['id']
        assert rows['Shelf bin']['parent_id'] == shelf['id']

    def test_a_root_location_hands_its_children_the_root(self, client, auth_headers):
        """The boundary of the same rule: a location at the root has no
        parent to hand down, so its children become roots themselves.

        Documenting, not discriminating: for a node already at the root,
        reparenting the children to the deleted node's parent and the
        ``SET NULL`` fallback produce the same result, so this test passes
        with and without the reparenting update in place. The test that
        fails without it is the nested one above."""
        site = self._create_location(client, auth_headers, 'Site')
        self._create_location(client, auth_headers, 'Zone', site['id'])

        response = client.delete(
            f'/api/v1/locations/{site["id"]}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert self._rows(client, auth_headers)['Zone']['parent_id'] is None

    def test_delete_storage_success(
        self, client, auth_headers, db_session, test_user, test_storage_type
    ):
        """Tests successful storage location deletion."""
        # Create location to delete
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='To delete',
        )
        db_session.add(storage)
        db_session.commit()

        response = client.delete(
            f'/api/v1/locations/{storage.id}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_storage_not_found(self, client, auth_headers):
        """Tests deleting non-existent storage location."""
        from uuid import uuid4

        response = client.delete(f'/api/v1/locations/{uuid4()}', headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_storage_referenced_by_stock_moves_returns_400(
        self, client, auth_headers, db_session, test_user, test_storage_type
    ):
        """Regression: deleting a storage referenced by StockMove ledger rows
        must be rejected at the application level.

        Background: the stock_moves FK on from_location_id / to_location_id
        uses ON DELETE SET NULL, but the ck_stock_moves_at_least_one_location
        CHECK constraint forbids both columns from being NULL simultaneously.
        Without an application guard, the cascading UPDATE fails with a
        CheckViolationError. The fix in delete_storage raises ValueError
        ("Cannot delete storage location referenced by N stock movement(s)...")
        which the router maps to 409 Conflict (not a 500).
        """
        from uuid import uuid4

        from app.models.product_template import ProductTemplate
        from app.models.stock_move import (
            StockMove,
            StockMoveReferenceType,
            StockMoveState,
        )
        from app.models.storage_location import StorageLocation

        location = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='StockMove referenced location',
        )
        db_session.add(location)
        db_session.flush()

        template = ProductTemplate(
            organization_id=test_user.organization_id,
            name='Test template',
        )
        db_session.add(template)
        db_session.flush()

        # Insert a stock_move referencing the location via from_location_id.
        # to_location_id is NULL — this is exactly the row pattern that
        # would trigger the CHECK constraint on cascading DELETE.
        move = StockMove(
            organization_id=test_user.organization_id,
            product_template_id=template.id,
            from_location_id=location.id,
            to_location_id=None,
            quantity=__import__('decimal').Decimal('10'),
            state=StockMoveState.DONE,
            reference_type=StockMoveReferenceType.ITEM,
            reference_id=uuid4(),
            created_by=test_user.id,
        )
        db_session.add(move)
        db_session.commit()

        response = client.delete(
            f'/api/v1/locations/{location.id}', headers=auth_headers
        )

        # Application guard rejects with 409 (ValueError → ConflictException).
        assert response.status_code == status.HTTP_409_CONFLICT
        body = response.json()
        # ConflictException uses a structured detail: {'code': '...', 'message': '...'}
        detail = body['detail']
        if isinstance(detail, dict):
            message = detail.get('message', '')
        else:
            message = detail
        assert 'stock movement' in message.lower()


@pytest.mark.integration
class TestStorageSummary:
    """Tests for storage location summary endpoint."""

    def test_get_storage_summary(
        self, client, auth_headers, test_storage_location, test_items_batch
    ):
        """Tests successful storage location summary fetching."""
        response = client.get(
            f'/api/v1/locations/{test_storage_location.id}/summary',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['id'] == str(test_storage_location.id)
        assert data['name'] == test_storage_location.name
        assert data['items_count'] >= 5
        assert 'expiring_soon_count' in data

    def test_get_storage_summary_empty(
        self, client, auth_headers, db_session, test_user, test_storage_type
    ):
        """Tests empty storage location summary."""
        # Create empty location
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='Empty storage',
        )
        db_session.add(storage)
        db_session.commit()

        response = client.get(
            f'/api/v1/locations/{storage.id}/summary', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['items_count'] == 0
        assert data['expiring_soon_count'] == 0

    def test_get_storage_summary_not_found(self, client, auth_headers):
        """Tests fetching summary of non-existent location."""
        from uuid import uuid4

        response = client.get(
            f'/api/v1/locations/{uuid4()}/summary', headers=auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_storage_summary_subtree_items_count(
        self, client, auth_headers, db_session, test_user
    ):
        """subtree_items_count covers descendants; items_count stays direct-only."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        zone = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='Zone',
        )
        db_session.add(zone)
        db_session.flush()
        child = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='Child shelf',
            parent_id=zone.id,
        )
        db_session.add(child)
        db_session.flush()
        db_session.add(
            Item(
                organization_id=test_user.organization_id,
                storage_location_id=child.id,
                name='Milk',
                quantity=1,
            )
        )
        db_session.commit()

        response = client.get(
            f'/api/v1/locations/{zone.id}/summary', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['items_count'] == 0
        assert data['subtree_items_count'] == 1


@pytest.mark.integration
class TestStorageItems:
    """Tests for items in storage location endpoint."""

    def test_get_storage_items(
        self, client, auth_headers, test_storage_location, test_items_batch
    ):
        """Tests successful items fetching in storage location."""
        response = client.get(
            f'/api/v1/locations/{test_storage_location.id}/items', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()['items']
        assert len(items) >= 5

    def test_get_storage_items_empty(
        self, client, auth_headers, db_session, test_user, test_storage_type
    ):
        """Tests fetching items from empty storage location."""
        # Create empty location
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='Empty storage',
        )
        db_session.add(storage)
        db_session.commit()

        response = client.get(
            f'/api/v1/locations/{storage.id}/items', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()['items']
        assert len(items) == 0

    def test_get_storage_items_with_uom_serializes(
        self, client, auth_headers, db_session, test_storage_location, test_user
    ):
        """Regression: items with a UoM must serialize without a 500.

        The endpoint returns ItemDTO (CoreAPI) but validates against
        ItemSchema, whose uom mapping used to call
        from_orm_with_category on a UomDTO — which has no `category`
        relation — raising AttributeError for every location whose items
        have a unit of measure.
        """
        from app.models.item import Item
        from app.models.uom import Uom, UomCategory

        category = UomCategory(organization_id=test_user.organization_id, name='Weight')
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
        db_session.flush()
        db_session.add(
            Item(
                organization_id=test_storage_location.organization_id,
                storage_location_id=test_storage_location.id,
                name='With uom',
                quantity=2,
                uom_id=uom.id,
            )
        )
        db_session.commit()

        response = client.get(
            f'/api/v1/locations/{test_storage_location.id}/items',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()['items']
        with_uom = next(item for item in items if item['name'] == 'With uom')
        assert with_uom['uom']['symbol'] == 'kg'

    def test_include_inside_adds_the_items_of_every_place_below(
        self, client, auth_headers, db_session, test_user, test_storage_type
    ):
        """One ask for the subtree: the shelf, the rack under it and a sibling."""
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        def place(name, parent=None):
            row = StorageLocation(
                organization_id=test_user.organization_id,
                created_by=test_user.id,
                storage_type_id=test_storage_type.id,
                name=name,
                parent_id=parent.id if parent else None,
            )
            db_session.add(row)
            db_session.flush()
            return row

        zone = place('Zone')
        rack = place('Rack', zone)
        shelf = place('Shelf', rack)
        sibling = place('Sibling zone')
        for where, name in (
            (zone, 'On the zone'),
            (shelf, 'On the shelf'),
            (sibling, 'Next door'),
        ):
            db_session.add(
                Item(
                    organization_id=test_user.organization_id,
                    storage_location_id=where.id,
                    name=name,
                    quantity=1,
                )
            )
        db_session.commit()

        own = client.get(f'/api/v1/locations/{zone.id}/items', headers=auth_headers)
        inside = client.get(
            f'/api/v1/locations/{zone.id}/items?include_inside=true',
            headers=auth_headers,
        )

        assert [i['name'] for i in own.json()['items']] == ['On the zone']
        assert {i['name'] for i in inside.json()['items']} == {
            'On the zone',
            'On the shelf',
        }

    def test_include_inside_pages_in_the_database(
        self, client, auth_headers, db_session, test_user, test_storage_type
    ):
        """A page of the subtree loads that page's items, not the subtree."""
        from sqlalchemy import event

        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        zone = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='Zone',
        )
        db_session.add(zone)
        db_session.flush()
        shelf = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='Shelf',
            parent_id=zone.id,
        )
        db_session.add(shelf)
        db_session.flush()
        for index in range(5):
            db_session.add(
                Item(
                    organization_id=test_user.organization_id,
                    storage_location_id=(zone if index % 2 else shelf).id,
                    name=f'Product {index}',
                    quantity=1,
                )
            )
        db_session.commit()

        hydrated: list[int] = []
        batch: list[object] = []

        def count_load(target, _context):
            batch.append(target)

        event.listen(Item, 'load', count_load)
        names: list[str] = []
        try:
            for offset in (0, 2, 4):
                batch.clear()
                page = client.get(
                    f'/api/v1/locations/{zone.id}/items'
                    f'?include_inside=true&limit=2&offset={offset}',
                    headers=auth_headers,
                ).json()
                hydrated.append(len(batch))
                names += [i['name'] for i in page['items']]
                assert page['total'] == 5
                assert page['has_more'] is (offset < 4)
        finally:
            event.remove(Item, 'load', count_load)

        assert sorted(names) == [f'Product {i}' for i in range(5)]
        assert max(hydrated) <= 2

    def test_get_storage_items_not_found(self, client, auth_headers):
        """Tests fetching items from non-existent location."""
        from uuid import uuid4

        response = client.get(
            f'/api/v1/locations/{uuid4()}/items', headers=auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestStoragePrint:
    """Tests for storage label printing endpoint."""

    def test_print_storage_label_success(
        self, client, auth_headers, db_session, test_storage_location
    ):
        """Tests successful storage label generation."""
        # Ensure it has a short_code
        if not test_storage_location.short_code:
            test_storage_location.short_code = 'LOC-TEST-123'
            db_session.add(test_storage_location)
            db_session.commit()
            db_session.refresh(test_storage_location)

        response = client.get(
            f'/api/v1/locations/{test_storage_location.id}/print', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.headers['content-type'] == 'image/png'
        assert len(response.content) > 0

    def test_print_storage_label_no_code(
        self, client, auth_headers, db_session, test_user, test_storage_type
    ):
        """Tests printing storage label without a short_code returns 400.

        When short_code is None the endpoint returns 400 — user must generate
        a code first via POST /locations/{id}/generate-code.
        """
        import uuid

        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='No Code Storage',
            short_code=None,  # Explicitly None
        )
        db_session.add(storage)
        db_session.commit()

        response = client.get(
            f'/api/v1/locations/{storage.id}/print', headers=auth_headers
        )

        # No short_code → 400, user must generate a code first
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
class TestStorageTree:
    """Tests for storage location tree endpoint."""

    def test_get_tree_flat(self, client, auth_headers, test_storage_location):
        """Tests tree endpoint with a flat (no parent) location."""
        response = client.get('/api/v1/locations/tree', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        tree = response.json()
        assert isinstance(tree, list)
        # Root node should be present
        ids = [n['id'] for n in tree]
        assert str(test_storage_location.id) in ids

    def test_get_tree_hierarchical(
        self, client, auth_headers, db_session, test_user, test_storage_type
    ):
        """Tests tree endpoint with parent-child hierarchy."""
        from app.models.storage_location import StorageLocation

        parent = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='Parent Location',
        )
        db_session.add(parent)
        db_session.flush()

        child = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='Child Location',
            parent_id=parent.id,
        )
        db_session.add(child)
        db_session.commit()

        response = client.get('/api/v1/locations/tree', headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        tree = response.json()

        parent_node = next((n for n in tree if n['id'] == str(parent.id)), None)
        assert parent_node is not None
        child_ids = [c['id'] for c in parent_node['children']]
        assert str(child.id) in child_ids

    def test_get_tree_unauthorized(self, client):
        """Tests tree endpoint without authorization."""
        response = client.get('/api/v1/locations/tree')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_tree_items_count_counts_records_not_units(
        self, client, auth_headers, db_session, test_user, test_storage_type
    ):
        """items_count on a tree node counts product records, not units.

        The card under the number said "pcs." — a caption for a quantity the
        query never measured. Two products of five and one unit are two
        positions, and stay two when a unit is added to a product.
        """
        from app.models.item import Item
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='Counted shelf',
        )
        db_session.add(storage)
        db_session.flush()
        db_session.add_all(
            [
                Item(
                    organization_id=test_user.organization_id,
                    storage_location_id=storage.id,
                    name='Big pack',
                    quantity=5,
                ),
                Item(
                    organization_id=test_user.organization_id,
                    storage_location_id=storage.id,
                    name='Single',
                    quantity=1,
                ),
            ]
        )
        db_session.commit()

        tree = client.get('/api/v1/locations/tree', headers=auth_headers).json()
        node = next(n for n in tree if n['id'] == str(storage.id))
        assert node['items_count'] == 2

    def test_get_tree_usage_all_includes_virtual(
        self, client, auth_headers, db_session, test_user, test_storage_type
    ):
        """usage=all reaches the virtual counterparts the internal default hides.

        The storages screen needs them reachable — the edit switch is the only
        way back from a mis-set purpose — while the default tree keeps them
        away from pickers and dashboards.
        """
        from app.models.storage_location import LocationUsage, StorageLocation

        virtual = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='Consumed (Virtual)',
            usage=LocationUsage.CUSTOMER,
        )
        db_session.add(virtual)
        db_session.commit()

        default_tree = client.get('/api/v1/locations/tree', headers=auth_headers).json()
        full_tree = client.get(
            '/api/v1/locations/tree',
            params={'usage': 'all'},
            headers=auth_headers,
        ).json()

        default_ids = [n['id'] for n in default_tree]
        all_ids = [n['id'] for n in full_tree]
        assert str(virtual.id) not in default_ids
        assert str(virtual.id) in all_ids
        assert any(n['usage'] == 'customer' for n in full_tree)


@pytest.mark.integration
class TestStorageBreadcrumb:
    """Tests for storage breadcrumb endpoint."""

    def test_get_breadcrumb_root(self, client, auth_headers, test_storage_location):
        """Tests breadcrumb for a root location (no parent)."""
        response = client.get(
            f'/api/v1/locations/{test_storage_location.id}/breadcrumb',
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        crumbs = response.json()
        assert len(crumbs) == 1
        assert crumbs[0]['id'] == str(test_storage_location.id)
        assert crumbs[0]['name'] == test_storage_location.name

    def test_get_breadcrumb_nested(
        self, client, auth_headers, db_session, test_user, test_storage_type
    ):
        """Tests breadcrumb for a nested location (grandparent > parent > child)."""
        from app.models.storage_location import StorageLocation

        root = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='Site',
        )
        db_session.add(root)
        db_session.flush()

        middle = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='Zone',
            parent_id=root.id,
        )
        db_session.add(middle)
        db_session.flush()

        leaf = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            storage_type_id=test_storage_type.id,
            name='Shelf',
            parent_id=middle.id,
        )
        db_session.add(leaf)
        db_session.commit()

        response = client.get(
            f'/api/v1/locations/{leaf.id}/breadcrumb', headers=auth_headers
        )
        assert response.status_code == status.HTTP_200_OK
        crumbs = response.json()
        assert len(crumbs) == 3
        assert crumbs[0]['name'] == 'Site'
        assert crumbs[1]['name'] == 'Zone'
        assert crumbs[2]['name'] == 'Shelf'

    def test_get_breadcrumb_not_found(self, client, auth_headers):
        """Tests breadcrumb for non-existent location."""
        from uuid import uuid4

        response = client.get(
            f'/api/v1/locations/{uuid4()}/breadcrumb', headers=auth_headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
