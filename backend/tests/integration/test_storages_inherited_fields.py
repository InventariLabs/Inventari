"""Product fields set on a location apply to every location inside it.

Tracked and custom product fields could be set on any level, but nothing
read them from above: an organization that wanted "Opened on" on every shelf
of a rack set it on each shelf, and a shelf added later started without it.
The storages listing now names, for every location, the fields it takes from
the locations above it and where each comes from — the product form asks for
those as well as the location's own.
"""

import pytest
from fastapi import status

STORAGES = '/api/v1/locations'


def _create(client, headers, name, parent_id=None, **fields):
    response = client.post(
        STORAGES,
        headers=headers,
        json={'name': name, 'parent_id': parent_id, **fields},
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return response.json()['id']


def _row(client, headers, storage_id):
    response = client.get(STORAGES, headers=headers)
    assert response.status_code == status.HTTP_200_OK
    return next(s for s in response.json()['items'] if s['id'] == storage_id)


@pytest.mark.integration
class TestInheritedLocationFields:
    def test_a_shelf_takes_the_fields_of_every_level_above_it(
        self, client, auth_headers
    ):
        warehouse = _create(
            client,
            auth_headers,
            'Warehouse',
            context_schema=['barcode'],
            field_definitions=[
                {'key': 'opened_on', 'label': 'Opened on', 'type': 'date'}
            ],
        )
        rack = _create(
            client,
            auth_headers,
            'Rack',
            warehouse,
            context_schema=['notes'],
            field_definitions=[
                {'key': 'supplier', 'label': 'Supplier', 'type': 'text'}
            ],
        )
        shelf = _create(client, auth_headers, 'Shelf', rack)

        row = _row(client, auth_headers, shelf)

        assert row['context_schema'] == []
        assert row['field_definitions'] == []
        assert row['inherited_context_schema'] == [
            {'key': 'notes', 'from_id': rack, 'from_name': 'Rack'},
            {'key': 'barcode', 'from_id': warehouse, 'from_name': 'Warehouse'},
        ]
        assert [
            (f['key'], f['label'], f['from_id'], f['from_name'])
            for f in row['inherited_field_definitions']
        ] == [
            ('supplier', 'Supplier', rack, 'Rack'),
            ('opened_on', 'Opened on', warehouse, 'Warehouse'),
        ]

    def test_the_nearest_definition_wins_a_name_clash(self, client, auth_headers):
        warehouse = _create(
            client,
            auth_headers,
            'Depot',
            context_schema=['barcode'],
            field_definitions=[{'key': 'batch', 'label': 'Batch', 'type': 'text'}],
        )
        rack = _create(
            client,
            auth_headers,
            'Cold rack',
            warehouse,
            context_schema=['barcode'],
            field_definitions=[
                {
                    'key': 'batch',
                    'label': 'Batch number',
                    'type': 'text',
                    'required': True,
                }
            ],
        )
        shelf = _create(client, auth_headers, 'Bottom shelf', rack)

        row = _row(client, auth_headers, shelf)

        assert row['inherited_context_schema'] == [
            {'key': 'barcode', 'from_id': rack, 'from_name': 'Cold rack'}
        ]
        [batch] = row['inherited_field_definitions']
        assert (batch['label'], batch['required'], batch['from_name']) == (
            'Batch number',
            True,
            'Cold rack',
        )

    def test_a_location_inherits_nothing_of_its_own_fields_and_a_root_nothing(
        self, client, auth_headers
    ):
        """The inherited lists name what comes from above, never the own list."""
        root = _create(
            client,
            auth_headers,
            'Garage',
            context_schema=['price'],
            field_definitions=[{'key': 'colour', 'label': 'Colour'}],
        )

        row = _row(client, auth_headers, root)

        assert row['context_schema'] == ['price']
        assert row['inherited_context_schema'] == []
        assert row['inherited_field_definitions'] == []

    def test_a_field_the_location_sets_itself_is_not_also_inherited(
        self, client, auth_headers
    ):
        """The own definition wins the clash, so there is nothing left to
        take from above — the settings list used to show one field twice,
        own and "Set on a level above"."""
        warehouse = _create(
            client,
            auth_headers,
            'Warehouse',
            context_schema=['notes'],
            field_definitions=[
                {'key': 'supplier', 'label': 'Supplier', 'type': 'text'}
            ],
        )
        shelf = _create(
            client,
            auth_headers,
            'Shelf',
            warehouse,
            context_schema=['notes'],
            field_definitions=[
                {'key': 'supplier', 'label': 'Supplier here', 'type': 'text'}
            ],
        )

        row = _row(client, auth_headers, shelf)

        assert row['context_schema'] == ['notes']
        assert row['inherited_context_schema'] == []
        assert row['inherited_field_definitions'] == []
