"""A category's required custom field is a rule, not a hint of the add form.

The add form refused a product without the field; the API created it with
``meta_data {}`` and the import filed the row, and the next person to edit
such a product was blocked by a field they had never seen.
"""

import pytest
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

ITEM_URL = '/api/v1/items'


def _fasteners(client, auth_headers) -> dict:
    response = client.post(
        '/api/v1/categories',
        headers=auth_headers,
        json={
            'name': 'Fasteners',
            'field_definitions': [
                {
                    'key': 'thread_size',
                    'label': 'Thread size',
                    'type': 'select',
                    'options': ['M6', 'M8'],
                    'required': True,
                },
                {'key': 'finish', 'label': 'Finish', 'type': 'text'},
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _post(client, auth_headers, shelf, category, metadata=None):
    body = {
        'name': 'Hex bolt',
        'quantity': 3,
        'location_id': str(shelf.id),
        'category_id': category['id'],
    }
    if metadata is not None:
        body['metadata'] = metadata
    return client.post(ITEM_URL, headers=auth_headers, json=body)


def test_the_api_refuses_a_product_without_the_required_field_naming_it(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    category = _fasteners(client, auth_headers)

    response = _post(client, auth_headers, test_storage_location, category)

    assert response.status_code == 400, response.text
    assert 'Thread size' in response.text


def test_an_empty_value_is_as_missing_as_no_value(
    client, auth_headers, test_storage_location
) -> None:
    category = _fasteners(client, auth_headers)

    response = _post(
        client,
        auth_headers,
        test_storage_location,
        category,
        {'thread_size': '  '},
    )

    assert response.status_code == 400, response.text


def test_a_product_that_fills_the_field_is_created(
    client, auth_headers, test_storage_location
) -> None:
    category = _fasteners(client, auth_headers)

    response = _post(
        client,
        auth_headers,
        test_storage_location,
        category,
        {'thread_size': 'M8'},
    )

    assert response.status_code == 201, response.text
    assert response.json()['metadata']['thread_size'] == 'M8'


def test_a_category_without_required_fields_asks_for_nothing(
    client, auth_headers, test_storage_location, test_category
) -> None:
    response = client.post(
        ITEM_URL,
        headers=auth_headers,
        json={
            'name': 'Loin',
            'quantity': 1,
            'location_id': str(test_storage_location.id),
            'category_id': str(test_category.id),
        },
    )

    assert response.status_code == 201, response.text
