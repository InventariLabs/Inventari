"""
Integration tests for items API endpoints.

Tests verify correctness of endpoints:
- GET /api/v1/items - list of items with filters
- POST /api/v1/items - create item
- GET /api/v1/items/expiring - expiring items
- GET /api/v1/items/{item_id} - item details
- PUT /api/v1/items/{item_id} - update item
- DELETE /api/v1/items/{item_id} - delete item
- PATCH /api/v1/items/{item_id}/quantity - change quantity
- PATCH /api/v1/items/{item_id}/move - move item
- GET /api/v1/items/export/xlsx - export items to Excel
"""

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status

from tests.integration._shelf import anchor_pending_records


@pytest.mark.integration
class TestItemsList:
    """Tests for items list endpoint."""

    def test_get_items_empty(self, client, auth_headers):
        """Tests fetching empty items list."""
        response = client.get('/api/v1/items', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['items'] == []
        assert data['total'] == 0
        assert data['has_more'] is False

    def test_get_items_with_data(self, client, auth_headers, test_items_batch):
        """Tests fetching items list with data."""
        response = client.get('/api/v1/items', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        items = data['items']
        assert data['total'] == 5
        assert len(items) == 5
        names = {i['name'] for i in items}
        assert names == {f'Product {i + 1}' for i in range(5)}

    def test_list_with_poisoned_quantity_row_stays_readable(
        self, client, auth_headers, test_item, db_session
    ):
        """A row whose quantity is already NaN must not take the page down.

        The poison predates the write gate. The `quantity >= 0`
        CHECK passes NaN (PostgreSQL sorts NaN above every number), so such a
        row can exist; the list reads it as the import default instead of
        refusing every result page it lands on."""
        from sqlalchemy import text

        db_session.execute(
            text("UPDATE items SET quantity = 'NaN'::numeric WHERE id = :id"),
            {'id': str(test_item.id)},
        )
        db_session.commit()

        response = client.get('/api/v1/items?limit=200', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        poisoned = next(
            i for i in response.json()['items'] if i['id'] == str(test_item.id)
        )
        assert Decimal(poisoned['quantity']) == 1.0

    def test_get_items_filter_by_storage(
        self, client, auth_headers, test_item, test_storage_location
    ):
        """Tests filtering items by storage location."""
        response = client.get(
            f'/api/v1/items?location_id={test_storage_location.id}',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        items = data['items']
        assert len(items) >= 1
        assert any(item['id'] == str(test_item.id) for item in items)

    def test_get_items_by_virtual_storage_reaches_consumed_item(
        self, client, auth_headers, test_item, test_user, test_storage_type, db_session
    ):
        """An explicit storage_id reaches past the internal default.

        Consuming the last unit moves the record into the organization's
        virtual 'Consumed' location, where the internal-only default hid it
        from every list; the location's own "Open" is the way back.
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
        db_session.flush()
        test_item.storage_location_id = virtual.id
        test_item.quantity = 0
        db_session.commit()

        default_response = client.get('/api/v1/items', headers=auth_headers)
        assert default_response.status_code == status.HTTP_200_OK
        default_ids = [i['id'] for i in default_response.json()['items']]
        assert str(test_item.id) not in default_ids

        filtered = client.get(
            f'/api/v1/items?location_id={virtual.id}', headers=auth_headers
        )
        assert filtered.status_code == status.HTTP_200_OK
        filtered_ids = [i['id'] for i in filtered.json()['items']]
        assert str(test_item.id) in filtered_ids

    def test_include_empty_reaches_the_consumed_record_without_an_address(
        self, client, auth_headers, test_item, test_user, test_storage_type, db_session
    ):
        """The list's own "show used up" widens past the internal default.

        Consuming the last unit files the record under the virtual Consumed
        location, so the default list (internal only) hides it and the one
        way back ran through the storage tree. ``include_empty``
        is the list answering for itself: a record with nothing left joins
        the rows without the reader naming where it sits, and the footer
        sums widen with the rows they describe.
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
        db_session.flush()
        test_item.storage_location_id = virtual.id
        test_item.quantity = 0
        db_session.commit()

        default_response = client.get('/api/v1/items', headers=auth_headers)
        assert default_response.status_code == status.HTTP_200_OK
        default_ids = [i['id'] for i in default_response.json()['items']]
        assert str(test_item.id) not in default_ids
        assert default_response.json()['total'] == 0

        widened = client.get('/api/v1/items?include_empty=true', headers=auth_headers)
        assert widened.status_code == status.HTTP_200_OK
        widened_data = widened.json()
        assert str(test_item.id) in [i['id'] for i in widened_data['items']]
        assert widened_data['total'] == 1

        # The footer reads the same filters, so it widens with the rows —
        # one source, no sums describing a list the reader cannot see.
        aggregates = client.get(
            '/api/v1/items/aggregates?include_empty=true', headers=auth_headers
        )
        assert aggregates.status_code == status.HTTP_200_OK
        assert aggregates.json()['count'] == 1

    def test_get_items_filter_by_category(
        self, client, auth_headers, test_item, test_category
    ):
        """Tests filtering items by category."""
        response = client.get(
            f'/api/v1/items?category_id={test_category.id}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        items = data['items']
        assert len(items) >= 1
        assert any(item['id'] == str(test_item.id) for item in items)

    def test_get_items_filter_by_expiring(self, client, auth_headers, test_item):
        """Tests filtering expiring items."""
        # Create item expiring within 7 days
        response = client.get('/api/v1/items?expiring_days=7', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        items = data['items']
        # Check that all items have expiry date within 7 days
        for item in items:
            if item['expiry_date']:
                expiry_date = date.fromisoformat(item['expiry_date'])
                assert expiry_date <= date.today() + timedelta(days=7)

    def test_get_items_filter_by_template_ids(
        self, client, auth_headers, db_session, test_user, test_storage_location
    ):
        """A neutral filter: narrow the list to a set of product templates.

        Modules use it to express their own question — "which products have a
        formula" comes from maker, and Core only has to accept the answer.
        """
        from app.models.item import Item
        from app.models.product_template import ProductTemplate

        templates = []
        for name in ('Wanted', 'Other'):
            template = ProductTemplate(
                organization_id=test_user.organization_id, name=f'{name} template'
            )
            db_session.add(template)
            anchor_pending_records(db_session)
            db_session.flush()
            templates.append(template)
            db_session.add(
                Item(
                    name=f'{name} product',
                    quantity=1,
                    organization_id=test_user.organization_id,
                    storage_location_id=test_storage_location.id,
                    template_id=template.id,
                )
            )
        anchor_pending_records(db_session)
        db_session.commit()

        response = client.get(
            f'/api/v1/items?template_ids={templates[0].id}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        names = {item['name'] for item in response.json()['items']}
        assert names == {'Wanted product'}

    def test_get_items_template_ids_accepts_several(
        self, client, auth_headers, db_session, test_user, test_storage_location
    ):
        from app.models.item import Item
        from app.models.product_template import ProductTemplate

        ids = []
        for name in ('A', 'B', 'C'):
            template = ProductTemplate(
                organization_id=test_user.organization_id, name=f'{name} template'
            )
            db_session.add(template)
            anchor_pending_records(db_session)
            db_session.flush()
            ids.append(template.id)
            db_session.add(
                Item(
                    name=f'{name} product',
                    quantity=1,
                    organization_id=test_user.organization_id,
                    storage_location_id=test_storage_location.id,
                    template_id=template.id,
                )
            )
        anchor_pending_records(db_session)
        db_session.commit()

        response = client.get(
            f'/api/v1/items?template_ids={ids[0]},{ids[2]}', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        names = {item['name'] for item in response.json()['items']}
        assert names == {'A product', 'C product'}

    def test_get_items_empty_template_ids_is_not_a_filter(
        self, client, auth_headers, test_items_batch
    ):
        """An empty value must not silently return nothing — a chip that has
        not loaded its ids yet would blank the whole list."""
        response = client.get('/api/v1/items?template_ids=', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['total'] == 5

    @pytest.mark.parametrize(
        'path',
        [
            '/api/v1/items',
            '/api/v1/items/aggregates',
            '/api/v1/items/export/xlsx',
        ],
    )
    def test_malformed_template_ids_get_a_translated_refusal(
        self, client, auth_headers, path, caplog
    ):
        """The UUID constructor's English never reaches the reader; the log has it."""
        with caplog.at_level(logging.WARNING):
            response = client.get(
                f'{path}?template_ids=not-a-uuid', headers=auth_headers
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'hexadecimal' not in response.text
        assert 'Invalid UUID format' in response.text
        assert any(
            'hexadecimal' in record.getMessage() and 'not-a-uuid' in record.getMessage()
            for record in caplog.records
        )

    def test_get_items_unauthorized(self, client):
        """Tests fetching list without authorization."""
        response = client.get('/api/v1/items')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestItemsCreate:
    """Tests for item creation endpoint."""

    def test_create_item_success(
        self, client, auth_headers, test_storage_location, test_category
    ):
        """Tests successful item creation."""
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'New product',
                'brand': 'New brand',
                'weight_value': 500.0,
                'quantity': 3,
                'expiry_date': (date.today() + timedelta(days=30)).isoformat(),
                'freeze_date': date.today().isoformat(),
                'shelf_location': 'Shelf 3',
                'location_id': str(test_storage_location.id),
                'category_id': str(test_category.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'New product'
        assert data['brand'] == 'New brand'
        assert Decimal(data['quantity']) == 3
        assert 'id' in data

    def test_create_item_minimal(self, client, auth_headers, test_storage_location):
        """Tests creating item with minimal data."""
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Minimal product',
                'location_id': str(test_storage_location.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'Minimal product'
        assert Decimal(data['quantity']) == 1  # default value

    def test_create_item_without_unit_defaults_to_piece(
        self, client, auth_headers, test_storage_location
    ):
        """A product created without a unit is counted in pieces.

        Odoo defaults Units, ERPNext mandates Default UoM, Zoho preselects —
        every serious inventory product answers "a quantity of *what*" for the
        user instead of asking. The default is applied by the service, so API
        and import paths get it too, not just the form."""
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Unitless product',
                'location_id': str(test_storage_location.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['uom'] is not None
        assert data['uom']['symbol'] == 'pcs'

    def test_create_item_keeps_an_explicit_unit(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """The default never overrides a unit the caller chose."""
        from sqlalchemy import select

        from app.models.uom import Uom

        kg = db_session.scalars(select(Uom).where(Uom.symbol == 'kg')).one()
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Weighed product',
                'quantity': 2,
                'location_id': str(test_storage_location.id),
                'uom_id': str(kg.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['uom']['symbol'] == 'kg'

    def test_create_item_without_unit_inherits_the_matched_templates_unit(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """A matched template is knowledge — the default yields to it.

        The template said kilograms and the record still landed in pieces:
        the record and its catalogue row contradicted each other about the
        unit, and the BoM convertibility guard — which reads the catalogue —
        checked a different number than the shelf held. The value a caller
        left unset is filled from what the app already knows about this
        product, not from what it defaults to for strangers."""
        from sqlalchemy import select

        from app.models.uom import Uom

        kg = db_session.scalars(select(Uom).where(Uom.symbol == 'kg')).one()
        client.post(
            '/api/v1/items/product-templates',
            headers=auth_headers,
            json={'name': 'Rye flour', 'uom_id': str(kg.id)},
        )
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Rye flour',
                'location_id': str(test_storage_location.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['uom']['symbol'] == 'kg'

    def test_create_item_fractional_quantity_without_unit_is_refused(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """The default is pieces, and pieces count whole.

        The unit is settled before the quantity is measured, so a request
        that names no unit is measured in the unit it lands with. It used to
        land after the gate: this same 0.5 came back 201 here while the same
        0.5 with ``uom_id: pcs`` spelled out came back 400."""
        from sqlalchemy import select

        from app.models.item import Item

        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Half of something',
                'quantity': 0.5,
                'location_id': str(test_storage_location.id),
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        assert 'pcs' in response.text
        assert (
            db_session.scalars(
                select(Item).where(Item.name == 'Half of something')
            ).first()
            is None
        )

    def test_create_item_keeps_the_module_namespace_it_was_sent_as_meta_data(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """A namespace sent as ``meta_data`` must land, not vanish behind a 201.

        The column, the module namespace convention and the core DTOs all
        call this ``meta_data``; the request schema only spelled it
        ``metadata``, so a caller following the documented name got 201 and a
        row without the namespace — a quiet half-write on the API edge. Both
        spellings reach the same column."""
        from sqlalchemy import select

        from app.models.item import Item

        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Asset by documented name',
                'location_id': str(test_storage_location.id),
                'meta_data': {'equipment': {'asset_tag': 'A-1'}},
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        item_id = response.json()['id']
        row = db_session.scalars(select(Item).where(Item.id == item_id)).one()
        equipment_ns = (row.meta_data or {}).get('equipment')
        assert equipment_ns is not None
        assert equipment_ns['asset_tag'] == 'A-1'
        # The write answered with what it wrote, so the caller can see it landed.
        assert response.json()['metadata']['equipment']['asset_tag'] == 'A-1'

    def test_create_item_keeps_the_module_namespace_it_was_sent_as_metadata(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """The spelling the forms use still lands — the half this bug was not.

        Guards only that direction: ``meta_data`` is pinned by the test above.
        """
        from sqlalchemy import select

        from app.models.item import Item

        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Asset by form name',
                'location_id': str(test_storage_location.id),
                'metadata': {'equipment': {'asset_tag': 'A-2'}},
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        row = db_session.scalars(
            select(Item).where(Item.id == response.json()['id'])
        ).one()
        equipment_ns = (row.meta_data or {}).get('equipment')
        assert equipment_ns is not None
        assert equipment_ns['asset_tag'] == 'A-2'

    def test_create_item_refuses_two_spellings_of_meta_data_at_once(
        self, client, auth_headers, test_storage_location
    ):
        """Both names at once is an answerable question, not a silent winner.

        One of them would have to be dropped; which one is exactly the class
        of quiet loss this endpoint owes a name for."""
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Asset named twice',
                'location_id': str(test_storage_location.id),
                'meta_data': {'equipment': {'asset_tag': 'A-3'}},
                'metadata': {'equipment': {'asset_tag': 'A-4'}},
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert 'meta_data' in response.text

    def test_create_item_invalid_storage(self, client, auth_headers):
        """Tests creating item with invalid storage."""
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={'name': 'Product', 'location_id': str(uuid4())},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_item_unauthorized(self, client, test_storage_location):
        """Tests creating item without authorization."""
        response = client.post(
            '/api/v1/items',
            json={
                'name': 'Product',
                'location_id': str(test_storage_location.id),
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestItemsExpiring:
    """Tests for expiring items endpoint."""

    def test_get_expiring_items(self, client, auth_headers, test_item):
        """Tests fetching expiring items."""
        response = client.get('/api/v1/items/expiring?days=30', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        items = response.json()['items']
        # Check that all items have expiry date
        for item in items:
            assert item['expiry_date'] is not None

    def test_get_expiring_items_custom_days(self, client, auth_headers):
        """Tests fetching expiring items with custom period."""
        response = client.get('/api/v1/items/expiring?days=60', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        items = response.json()['items']
        for item in items:
            if item['expiry_date']:
                expiry_date = date.fromisoformat(item['expiry_date'])
                assert expiry_date <= date.today() + timedelta(days=60)


@pytest.mark.integration
class TestItemDetails:
    """Tests for item details endpoint."""

    def test_get_item_success(self, client, auth_headers, test_item):
        """Tests successful item details fetching."""
        response = client.get(f'/api/v1/items/{test_item.id}', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['id'] == str(test_item.id)
        assert data['name'] == test_item.name
        assert data['brand'] == test_item.brand

    def test_get_item_not_found(self, client, auth_headers):
        """Tests fetching non-existent item."""
        response = client.get(f'/api/v1/items/{uuid4()}', headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_item_unauthorized(self, client, test_item):
        """Tests fetching item details without authorization."""
        response = client.get(f'/api/v1/items/{test_item.id}')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_archived_item_names_the_archive(self, client, auth_headers, test_item):
        """A soft-deleted product is in the archive, not nowhere.

        The detail screen answered "this product no longer exists" about a
        record sitting one click away with a Restore button under it. The
        404 keeps its status — the product is not part of the live lists —
        but carries a code the page can read and follow to the archive.
        """
        response = client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)
        assert response.status_code == status.HTTP_204_NO_CONTENT

        gone = client.get(f'/api/v1/items/{test_item.id}', headers=auth_headers)

        assert gone.status_code == status.HTTP_404_NOT_FOUND
        detail = gone.json()['detail']
        assert detail['code'] == 'ITEM_ARCHIVED'
        assert detail['message']

    def test_archived_item_refusal_speaks_the_readers_language(
        self, client, auth_headers, test_item
    ):
        client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)

        gone = client.get(
            f'/api/v1/items/{test_item.id}',
            headers={**auth_headers, 'Accept-Language': 'pl'},
        )

        detail = gone.json()['detail']
        assert detail['code'] == 'ITEM_ARCHIVED'
        assert detail['message'] == (
            'Produkt jest w archiwum i można go stamtąd przywrócić'
        )

    def test_get_archived_item_answers_the_include_archived_ask(
        self, client, auth_headers, test_item
    ):
        """A screen whose record stays reachable names the archive in the ask.

        The default read above stays the archive-pointing 404 — the live
        lists must keep hiding the row — but the Equipment card renders the
        record itself, Restore and Purge under it. Hiding the record from
        every reader and then linking to it from history is the dead end
        this ask removes."""
        response = client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)
        assert response.status_code == status.HTTP_204_NO_CONTENT

        archived = client.get(
            f'/api/v1/items/{test_item.id}?include_archived=true',
            headers=auth_headers,
        )

        assert archived.status_code == status.HTTP_200_OK
        body = archived.json()
        assert body['id'] == str(test_item.id)
        assert body['name'] == test_item.name
        assert body['is_deleted'] is True


@pytest.mark.integration
class TestItemUpdate:
    """Tests for item update endpoint."""

    def test_update_item_success(self, client, auth_headers, test_item):
        """Tests successful item update."""
        response = client.put(
            f'/api/v1/items/{test_item.id}',
            headers=auth_headers,
            json={'name': 'Updated product', 'quantity': 10},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['name'] == 'Updated product'
        assert Decimal(data['quantity']) == 10

    def test_update_item_partial(self, client, auth_headers, test_item):
        """Tests partial item update."""
        response = client.put(
            f'/api/v1/items/{test_item.id}', headers=auth_headers, json={'quantity': 5}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert Decimal(data['quantity']) == 5
        assert data['name'] == test_item.name  # unchanged

    def test_update_item_clears_category(self, client, auth_headers, test_item):
        """An explicit null takes the category off the record.

        A product without a category is a normal state — the products list
        filters by it — and this is the request the form now sends when the
        picker's "No category" is chosen. Dropping the key instead, which is
        what the form used to do, is indistinguishable from not having touched
        the field.
        """
        assert test_item.category_id is not None

        response = client.put(
            f'/api/v1/items/{test_item.id}',
            headers=auth_headers,
            json={'category_id': None},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['category_id'] is None

    def test_update_item_keeps_the_module_namespace_it_was_sent_as_meta_data(
        self, client, auth_headers, test_item, db_session
    ):
        """PUT owes the same answer as POST: the documented spelling lands.

        The create door's twin — ``meta_data`` was an unknown key here too,
        so the update answered 200 and the namespace never arrived. Guards
        that direction only; the ``metadata`` spelling is the one the forms
        send and is pinned by the create tests.
        """
        from sqlalchemy import select

        from app.models.item import Item

        response = client.put(
            f'/api/v1/items/{test_item.id}',
            headers=auth_headers,
            json={'meta_data': {'equipment': {'asset_tag': 'A-5'}}},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        row = db_session.scalars(select(Item).where(Item.id == test_item.id)).one()
        equipment_ns = (row.meta_data or {}).get('equipment')
        assert equipment_ns is not None
        assert equipment_ns['asset_tag'] == 'A-5'

    def test_update_item_not_found(self, client, auth_headers):
        """Tests updating non-existent item."""
        response = client.put(
            f'/api/v1/items/{uuid4()}', headers=auth_headers, json={'name': 'New name'}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_item_with_decimal_and_date(self, client, auth_headers, test_item):
        """Tests updating item with Decimal and Date fields (JSON bug reproduction)."""
        response = client.put(
            f'/api/v1/items/{test_item.id}',
            headers=auth_headers,
            json={
                'purchase_price': 2.75,
                'expiry_date': (date.today() + timedelta(days=45)).isoformat(),
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert float(data['purchase_price']) == 2.75
        assert data['expiry_date'] == (date.today() + timedelta(days=45)).isoformat()


@pytest.mark.integration
class TestItemDelete:
    """Tests for item deletion endpoint."""

    def test_delete_item_success(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        """Tests successful item deletion."""
        # Create item to delete
        from app.models.item import Item

        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='To delete',
        )
        db_session.add(item)
        db_session.commit()

        response = client.delete(f'/api/v1/items/{item.id}', headers=auth_headers)

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_item_with_poisoned_quantity_succeeds(
        self, client, auth_headers, db_session, test_item
    ):
        """A NaN quantity row deletes through the app.

        The history and audit JSONB snapshots serialize the value
        the column type healed on load — not float('nan'), which PostgreSQL's
        jsonb refuses and which used to 500 the delete."""
        from sqlalchemy import text

        db_session.execute(
            text("UPDATE items SET quantity = 'NaN'::numeric WHERE id = :id"),
            {'id': str(test_item.id)},
        )
        db_session.commit()

        response = client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_item_not_found(self, client, auth_headers):
        """Tests deleting non-existent item."""
        response = client.delete(f'/api/v1/items/{uuid4()}', headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_item_without_reservation_does_not_log_unaccounted(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
        caplog,
    ):
        """Regression for spurious 'N unaccounted' WARNING on item delete.

        When deleting an item that never had any reservations, the
        lifecycle used to call ``release_reservation_async(quantity=old_qty)``
        unconditionally — a release-by-quantity that has since been removed
        from the core API. It logged ``Could not fully release N for
        product ... — N unaccounted`` whenever no reserved_quantity
        existed, polluting logs with a misleading warning.

        After the fix, ``delete_item`` pre-checks whether any
        ``reserved_quantity > 0`` exists for the item's quant and skips
        the release call when none. This test asserts the warning is not
        emitted in the common no-reservation case.
        """
        import logging

        from app.models.item import Item

        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='To delete (no reservation)',
            quantity=10,
        )
        db_session.add(item)
        db_session.commit()

        with caplog.at_level(logging.WARNING, logger='app.services._stock_reservation'):
            response = client.delete(f'/api/v1/items/{item.id}', headers=auth_headers)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        unaccounted = [r for r in caplog.records if 'unaccounted' in r.getMessage()]
        assert unaccounted == [], (
            f'Expected no "unaccounted" warning for item without '
            f'reservation, got: {[r.getMessage() for r in unaccounted]}'
        )


@pytest.mark.integration
class TestItemQuantityUpdate:
    """Tests for item quantity update endpoint."""

    def test_update_quantity_success(self, client, auth_headers, test_item):
        """Tests successful quantity update."""
        response = client.patch(
            f'/api/v1/items/{test_item.id}/quantity',
            headers=auth_headers,
            json={'quantity': 15},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert Decimal(data['quantity']) == 15

    def test_update_quantity_to_zero(self, client, auth_headers, test_item):
        """Tests updating quantity to zero."""
        response = client.patch(
            f'/api/v1/items/{test_item.id}/quantity',
            headers=auth_headers,
            json={'quantity': 0},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert Decimal(data['quantity']) == 0


@pytest.mark.integration
class TestItemMove:
    """Tests for item move endpoint."""

    def test_move_item_success(
        self, client, auth_headers, test_item, test_storage_type_fridge, db_session
    ):
        """Tests successful item move."""
        # Create second storage location
        from app.models.storage_location import StorageLocation

        target_storage = StorageLocation(
            organization_id=test_item.storage_location.organization_id,
            created_by=test_item.storage_location.created_by,
            storage_type_id=test_storage_type_fridge.id,
            name='Kitchen fridge',
        )
        db_session.add(target_storage)
        db_session.commit()

        response = client.patch(
            f'/api/v1/items/{test_item.id}/move',
            headers=auth_headers,
            json={
                'to_location_id': str(target_storage.id),
                'notes': 'Moved to fridge',
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['location_id'] == str(target_storage.id)

    def test_move_item_invalid_storage(self, client, auth_headers, test_item):
        """Tests moving to invalid storage."""
        response = client.patch(
            f'/api/v1/items/{test_item.id}/move',
            headers=auth_headers,
            json={'to_location_id': str(uuid4())},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestItemsCostTracking:
    """Tests for cost tracking functionality."""

    def test_create_item_with_price(
        self, client, auth_headers, test_storage_location, test_category
    ):
        """Tests creating item with purchase price."""
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Product with price',
                'location_id': str(test_storage_location.id),
                'category_id': str(test_category.id),
                'quantity': 2,
                'purchase_price': 25.50,
                'currency': 'USD',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'Product with price'
        assert float(data['purchase_price']) == 25.50
        assert data['currency'] == 'USD'

    def test_create_item_without_price(
        self, client, auth_headers, test_storage_location
    ):
        """Tests creating item without price (should default to None and PLN)."""
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Product without price',
                'location_id': str(test_storage_location.id),
                'quantity': 1,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'Product without price'
        assert data['purchase_price'] is None
        assert data['currency'] == 'USD'

    def test_update_item_price(self, client, auth_headers, test_item):
        """Tests updating item with new price."""
        response = client.put(
            f'/api/v1/items/{test_item.id}',
            headers=auth_headers,
            json={'purchase_price': 15.00, 'currency': 'USD'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert float(data['purchase_price']) == 15.00
        assert data['currency'] == 'USD'


@pytest.mark.integration
class TestItemsConsume:
    """Tests for consume item endpoint."""

    def test_consume_item_success(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        """Tests successful item consumption."""
        from app.models.item import Item

        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='To consume',
            quantity=5,
            purchase_price=10.00,
        )
        db_session.add(item)
        db_session.commit()

        response = client.patch(
            f'/api/v1/items/{item.id}/consume',
            headers=auth_headers,
            json={'quantity': 2, 'reason': 'eaten', 'notes': 'Eaten for dinner'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert Decimal(data['quantity']) == 3  # 5 - 2 = 3

    def test_consume_item_full_quantity(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        """Tests consuming item with full quantity (should soft-delete)."""
        from app.models.item import Item

        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='To consume completely',
            quantity=2,
            purchase_price=20.00,
        )
        db_session.add(item)
        db_session.commit()

        response = client.patch(
            f'/api/v1/items/{item.id}/consume',
            headers=auth_headers,
            json={'quantity': 2, 'reason': 'eaten'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert Decimal(data['quantity']) == 0
        assert data['is_deleted'] == False
        assert data['location_id'] != str(test_storage_location.id)

    def test_consume_item_exceeds_quantity(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        """Tests consuming more than available quantity."""
        from app.models.item import Item

        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='Small quantity',
            quantity=1,
            purchase_price=5.00,
        )
        db_session.add(item)
        db_session.commit()

        response = client.patch(
            f'/api/v1/items/{item.id}/consume',
            headers=auth_headers,
            json={'quantity': 5, 'reason': 'eaten'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()['detail']['message']
        assert 'Not enough stock' in detail or 'Niewystarczająca' in detail


@pytest.mark.integration
class TestItemsDiscard:
    """Tests for discard item endpoint."""

    def test_discard_item_success(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        """Tests successful item discard."""
        from app.models.item import Item

        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='To discard',
            quantity=3,
            purchase_price=15.00,
        )
        db_session.add(item)
        db_session.commit()

        response = client.patch(
            f'/api/v1/items/{item.id}/discard',
            headers=auth_headers,
            json={'quantity': 1, 'reason': 'expired', 'notes': 'Expired'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert Decimal(data['quantity']) == 2  # 3 - 1 = 2

    def test_discard_item_full_quantity(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        """Tests discarding item with full quantity (should soft-delete)."""
        from app.models.item import Item

        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='To discard completely',
            quantity=1,
            purchase_price=8.00,
        )
        db_session.add(item)
        db_session.commit()

        response = client.patch(
            f'/api/v1/items/{item.id}/discard',
            headers=auth_headers,
            json={'quantity': 1, 'reason': 'damaged'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert Decimal(data['quantity']) == 0
        assert data['is_deleted'] == False
        assert data['location_id'] != str(test_storage_location.id)


@pytest.mark.integration
class TestItemsArchived:
    """Tests for archived items endpoint."""

    def test_get_archived_items_empty(self, client, auth_headers):
        """Tests fetching empty archived items list."""
        response = client.get('/api/v1/items/archived', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['items'] == []
        assert data['total'] == 0

    def test_get_archived_items_with_data(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        """Tests fetching archived items with data."""

        from app.models.item import Item

        item = Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='Archived product',
            quantity=0,
            is_deleted=True,
            deleted_at=datetime.now(UTC),
            deletion_reason='USED',
            purchase_price=10.00,
        )
        db_session.add(item)
        db_session.commit()

        response = client.get('/api/v1/items/archived', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        items = data['items']
        assert data['total'] >= 1
        assert len(items) >= 1
        assert any(item_data['name'] == 'Archived product' for item_data in items)

    def test_get_archived_items_search_finds_item_beyond_first_page(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        """Search runs server-side: a match outside the loaded page is found."""
        from app.models.item import Item

        now = datetime.now(UTC)
        db_session.add_all(
            (
                Item(
                    organization_id=test_user.organization_id,
                    storage_location_id=test_storage_location.id,
                    category_id=test_category.id,
                    name='Old Chair',
                    quantity=0,
                    is_deleted=True,
                    deleted_at=now,
                ),
                Item(
                    organization_id=test_user.organization_id,
                    storage_location_id=test_storage_location.id,
                    category_id=test_category.id,
                    name='Projector Tripod',
                    barcode='EQ-90210',
                    quantity=0,
                    is_deleted=True,
                    deleted_at=now,
                ),
            )
        )
        db_session.commit()

        # Page size 1: the match lives on the second page, the one a
        # client-side filter over the loaded rows could never reach.
        response = client.get(
            '/api/v1/items/archived',
            params={'search': 'Tripod', 'limit': 1},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['total'] == 1
        assert [i['name'] for i in data['items']] == ['Projector Tripod']

    def test_get_archived_items_search_matches_barcode(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        """Search reaches the code on the sticker, like the active list."""
        from app.models.item import Item

        db_session.add(
            Item(
                organization_id=test_user.organization_id,
                storage_location_id=test_storage_location.id,
                category_id=test_category.id,
                name='Projector Tripod',
                barcode='EQ-90210',
                quantity=0,
                is_deleted=True,
                deleted_at=datetime.now(UTC),
            )
        )
        db_session.commit()

        response = client.get(
            '/api/v1/items/archived',
            params={'search': '90210'},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['total'] == 1
        assert data['items'][0]['name'] == 'Projector Tripod'

    def test_get_archived_items_search_scoped_to_organization(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        """A matching archived item of another organization stays invisible."""
        from app.models.item import Item
        from app.models.organization import Organization
        from app.models.storage_location import StorageLocation

        other_org = Organization(name='Other Org')
        db_session.add(other_org)
        db_session.flush()
        other_storage = StorageLocation(
            organization_id=other_org.id,
            created_by=test_user.id,
            name='Other Freezer',
        )
        db_session.add(other_storage)
        db_session.flush()
        db_session.add(
            Item(
                organization_id=other_org.id,
                storage_location_id=other_storage.id,
                category_id=test_category.id,
                name='Projector Tripod',
                quantity=0,
                is_deleted=True,
                deleted_at=datetime.now(UTC),
            )
        )
        db_session.commit()

        response = client.get(
            '/api/v1/items/archived',
            params={'search': 'Tripod'},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['total'] == 0
        assert data['items'] == []

    def test_get_archived_items_without_search_keeps_full_listing(
        self,
        client,
        auth_headers,
        db_session,
        test_storage_location,
        test_category,
        test_user,
    ):
        """Without a search the endpoint lists the archive as before."""
        from app.models.item import Item

        now = datetime.now(UTC)
        db_session.add_all(
            (
                Item(
                    organization_id=test_user.organization_id,
                    storage_location_id=test_storage_location.id,
                    category_id=test_category.id,
                    name='Old Chair',
                    quantity=0,
                    is_deleted=True,
                    deleted_at=now,
                ),
                Item(
                    organization_id=test_user.organization_id,
                    storage_location_id=test_storage_location.id,
                    category_id=test_category.id,
                    name='Projector Tripod',
                    quantity=0,
                    is_deleted=True,
                    deleted_at=now,
                ),
            )
        )
        db_session.commit()

        response = client.get('/api/v1/items/archived', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['total'] == 2
        assert {i['name'] for i in data['items']} == {
            'Old Chair',
            'Projector Tripod',
        }


@pytest.mark.integration
class TestItemsExport:
    """Tests for items export endpoint."""

    def test_export_items_xlsx_success(self, client, auth_headers, test_items_batch):
        """Tests successful items export to XLSX."""
        response = client.get('/api/v1/items/export/xlsx', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert (
            response.headers['content-type']
            == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        assert len(response.content) > 0


@pytest.mark.integration
class TestItemsHistory:
    """Tests for item history endpoints."""

    def test_get_items_history_empty(self, client, auth_headers):
        """Tests fetching empty global history."""
        response = client.get('/api/v1/items/history', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['items'] == []
        assert data['has_more'] is False

    def test_get_items_history_with_data(
        self,
        client,
        auth_headers,
        db_session,
        test_item,
        test_user,
    ):
        """Tests fetching global history with data."""
        from app.models.item_history import ItemAction, ItemHistory

        entry = ItemHistory(
            item_id=test_item.id,
            organization_id=test_user.organization_id,
            user_id=test_user.id,
            action=ItemAction.CREATED.value,
            changes={'quantity': 2},
        )
        db_session.add(entry)
        db_session.commit()

        response = client.get('/api/v1/items/history', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) == 1
        assert data['items'][0]['action'] == 'CREATED'
        assert data['items'][0]['item_id'] == str(test_item.id)

    def test_get_item_history_empty(self, client, auth_headers, test_item):
        """Tests fetching history for item with no history entries."""
        response = client.get(
            f'/api/v1/items/{test_item.id}/history', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['items'] == []
        assert data['has_more'] is False

    def test_get_item_history_with_data(
        self,
        client,
        auth_headers,
        db_session,
        test_item,
        test_user,
    ):
        """Tests fetching history for specific item."""
        from app.models.item_history import ItemAction, ItemHistory

        entries = [
            ItemHistory(
                item_id=test_item.id,
                organization_id=test_user.organization_id,
                user_id=test_user.id,
                action=ItemAction.CREATED.value,
                changes={'quantity': 2},
            ),
            ItemHistory(
                item_id=test_item.id,
                organization_id=test_user.organization_id,
                user_id=test_user.id,
                action=ItemAction.QUANTITY_CHANGED.value,
                changes={'old': 2, 'new': 1},
            ),
        ]
        for entry in entries:
            db_session.add(entry)
        db_session.commit()

        response = client.get(
            f'/api/v1/items/{test_item.id}/history', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) == 2
        assert data['items'][0]['action'] == 'QUANTITY_CHANGED'
        assert data['items'][1]['action'] == 'CREATED'

    def test_history_names_the_actor_as_the_movements_do(
        self,
        client,
        auth_headers,
        db_session,
        test_item,
        test_user,
    ):
        """The same person is one name on the movements tab and in the history.

        The movements tab prints the full name and falls back to the e-mail;
        the history printed the e-mail alone, so one person read as two on
        one page.
        """
        from app.models.item_history import ItemAction, ItemHistory

        db_session.add(
            ItemHistory(
                item_id=test_item.id,
                organization_id=test_user.organization_id,
                user_id=test_user.id,
                action=ItemAction.CREATED.value,
                changes={'quantity': 2},
            )
        )
        db_session.commit()

        def names() -> tuple[str, str]:
            one = client.get(
                f'/api/v1/items/{test_item.id}/history', headers=auth_headers
            ).json()['items'][0]['user_name']
            every = client.get('/api/v1/items/history', headers=auth_headers).json()[
                'items'
            ][0]['user_name']
            return one, every

        assert names() == (test_user.full_name, test_user.full_name)

        test_user.full_name = None
        db_session.commit()
        assert names() == (test_user.email, test_user.email)

    def test_get_item_history_with_source_document(
        self,
        client,
        auth_headers,
        db_session,
        test_item,
        test_user,
    ):
        """Tests that history entry can have source_document_id set (nullable FK)."""
        from app.models.item_history import ItemAction, ItemHistory

        entry = ItemHistory(
            item_id=test_item.id,
            organization_id=test_user.organization_id,
            user_id=test_user.id,
            action=ItemAction.USED.value,
            changes={'qty': 1},
            source_document_id=None,
        )
        db_session.add(entry)
        db_session.commit()

        response = client.get(
            f'/api/v1/items/{test_item.id}/history', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) == 1
        assert data['items'][0]['source_document_id'] is None

    def test_get_item_history_pagination(
        self,
        client,
        auth_headers,
        db_session,
        test_item,
        test_user,
    ):
        """Tests pagination of item history."""
        from app.models.item_history import ItemAction, ItemHistory

        for i in range(5):
            entry = ItemHistory(
                item_id=test_item.id,
                organization_id=test_user.organization_id,
                user_id=test_user.id,
                action=ItemAction.UPDATED.value,
                changes={'update': i},
            )
            db_session.add(entry)
        db_session.commit()

        response = client.get(
            f'/api/v1/items/{test_item.id}/history?limit=2', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) == 2
        assert data['has_more'] is True
        assert data['next_cursor'] is not None

        response = client.get(
            f'/api/v1/items/{test_item.id}/history?limit=2&cursor={data["next_cursor"]}',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) == 2
        assert data['has_more'] is True

    def test_get_item_history_enriched_with_user_name(
        self,
        client,
        auth_headers,
        db_session,
        test_item,
        test_user,
    ):
        """Tests that history entries include the person's name (full name, e-mail without one) when the user exists."""
        from app.models.item_history import ItemAction, ItemHistory

        entry = ItemHistory(
            item_id=test_item.id,
            organization_id=test_user.organization_id,
            user_id=test_user.id,
            action=ItemAction.CREATED.value,
            changes={},
        )
        db_session.add(entry)
        db_session.commit()

        response = client.get(
            f'/api/v1/items/{test_item.id}/history', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) == 1
        assert data['items'][0]['user_name'] == test_user.full_name
        assert data['items'][0]['item_name'] == test_item.name

    def test_get_item_history_filters_by_organization(
        self,
        client,
        auth_headers,
        db_session,
        test_item,
        test_user,
    ):
        """Tests that item history only shows entries from user's organization."""
        from app.models.item_history import ItemAction, ItemHistory
        from app.models.organization import Organization

        other_org = Organization(name='Other Org')
        db_session.add(other_org)
        db_session.flush()

        entry = ItemHistory(
            item_id=test_item.id,
            organization_id=test_user.organization_id,
            user_id=test_user.id,
            action=ItemAction.CREATED.value,
            changes={},
        )
        db_session.add(entry)
        db_session.commit()

        response = client.get(
            f'/api/v1/items/{test_item.id}/history', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) == 1
        assert all(
            e['organization_id'] == str(test_user.organization_id)
            for e in data['items']
        )

    def test_get_item_history_not_found(self, client, auth_headers):
        """Tests 404 returned for non-existent item."""
        from uuid import uuid4

        response = client.get(f'/api/v1/items/{uuid4()}/history', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['items'] == []

    def test_get_item_history_unauthorized(self, client, test_item):
        """Tests that unauthorized request is rejected."""
        response = client.get(f'/api/v1/items/{test_item.id}/history')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
