"""Integration tests: item create/update validates meta_data against the
category's field_definitions.

``validate_field_value`` defines the type-specific value contract
for ``money`` / ``multi-select`` / ``select`` fields, but was not wired into the
item write path. These tests define the contract for that wiring: an item whose
``meta_data`` violates its category's field_definitions shape MUST be rejected
with HTTP 400 at the API boundary.
"""

import pytest
from fastapi import status

pytestmark = [pytest.mark.integration]


def _category_with_money_field(db_session, category_model, *, code='DEPOSIT_CAT'):
    """Create a category declaring a ``money`` field keyed ``deposit_value``."""
    cat = category_model(
        name='Deposit Category',
        code=code,
        context_tag=None,
        sort_order=10,
        field_definitions=[
            {
                'key': 'deposit_value',
                'type': 'money',
                'label': 'Kaucja',
                'visible': True,
                'required': False,
            }
        ],
    )
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)
    return cat


def _category_with_multiselect_field(
    db_session, category_model, *, code='ALLERGEN_CAT'
):
    """Create a category declaring a ``multi-select`` field with fixed options."""
    cat = category_model(
        name='Allergen Category',
        code=code,
        context_tag=None,
        sort_order=11,
        field_definitions=[
            {
                'key': 'allergens',
                'type': 'multi-select',
                'label': 'Alergeny',
                'visible': True,
                'required': False,
                'options': ['gluten', 'lactose', 'nuts'],
            }
        ],
    )
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)
    return cat


class TestItemCreateMetadataValidation:
    """POST /api/v1/items must reject meta_data that violates the category's
    field_definitions value-shape contract."""

    def test_create_item_with_valid_money_metadata_passes(
        self, client, auth_headers, test_storage_location, db_session
    ):
        from app.models.category import Category

        cat = _category_with_money_field(db_session, Category)
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Bottle',
                'quantity': 1,
                'unit': 'bottle',
                'location_id': str(test_storage_location.id),
                'category_id': str(cat.id),
                'metadata': {'deposit_value': {'amount': 0.5, 'currency': 'PLN'}},
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text

    def test_create_item_with_malformed_money_metadata_rejected(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """money field value must be {amount, currency}; a bare string is rejected."""
        from app.models.category import Category

        cat = _category_with_money_field(db_session, Category)
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Bottle',
                'quantity': 1,
                'unit': 'bottle',
                'location_id': str(test_storage_location.id),
                'category_id': str(cat.id),
                'metadata': {'deposit_value': 'fifty cents'},
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text

    def test_a_refused_field_value_speaks_the_readers_language(
        self, client, auth_headers, test_storage_location, db_session
    ):
        from app.models.category import Category

        cat = _category_with_money_field(db_session, Category)
        response = client.post(
            '/api/v1/items',
            headers={**auth_headers, 'Accept-Language': 'pl'},
            json={
                'name': 'Bottle',
                'quantity': 1,
                'unit': 'bottle',
                'location_id': str(test_storage_location.id),
                'category_id': str(cat.id),
                'metadata': {'deposit_value': 'fifty cents'},
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'FIELD_MONEY_SHAPE'
        assert detail['message'] == (
            'Pole „Kaucja” musi zawierać kwotę i walutę, nic więcej'
        )

    def test_a_value_outside_the_options_names_it_in_the_readers_language(
        self, client, auth_headers, test_storage_location, db_session
    ):
        from app.models.category import Category

        cat = _category_with_multiselect_field(db_session, Category)
        response = client.post(
            '/api/v1/items',
            headers={**auth_headers, 'Accept-Language': 'pl'},
            json={
                'name': 'Cookies',
                'quantity': 1,
                'unit': 'pack',
                'location_id': str(test_storage_location.id),
                'category_id': str(cat.id),
                'metadata': {'allergens': ['gluten', 'shellfish']},
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        assert response.json()['detail']['message'] == (
            'Wartość „shellfish” nie należy do opcji pola „Alergeny”: gluten, lactose, nuts'
        )

    def test_create_item_with_money_missing_currency_rejected(
        self, client, auth_headers, test_storage_location, db_session
    ):
        from app.models.category import Category

        cat = _category_with_money_field(db_session, Category)
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Bottle',
                'quantity': 1,
                'unit': 'bottle',
                'location_id': str(test_storage_location.id),
                'category_id': str(cat.id),
                'metadata': {'deposit_value': {'amount': 0.5}},
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text

    def test_create_item_with_multiselect_value_not_in_options_rejected(
        self, client, auth_headers, test_storage_location, db_session
    ):
        from app.models.category import Category

        cat = _category_with_multiselect_field(db_session, Category)
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Cookies',
                'quantity': 1,
                'unit': 'pack',
                'location_id': str(test_storage_location.id),
                'category_id': str(cat.id),
                'metadata': {'allergens': ['gluten', 'shellfish']},
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text

    def test_create_item_with_valid_multiselect_metadata_passes(
        self, client, auth_headers, test_storage_location, db_session
    ):
        from app.models.category import Category

        cat = _category_with_multiselect_field(db_session, Category)
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Cookies',
                'quantity': 1,
                'unit': 'pack',
                'location_id': str(test_storage_location.id),
                'category_id': str(cat.id),
                'metadata': {'allergens': ['gluten', 'lactose']},
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text

    def test_create_item_unknown_metadata_key_passes(
        self, client, auth_headers, test_storage_location, db_session
    ):
        """Keys not declared in any field_definition are left untouched
        (advisory schema, not a closed contract)."""
        from app.models.category import Category

        cat = _category_with_money_field(db_session, Category)
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Bottle',
                'quantity': 1,
                'unit': 'bottle',
                'location_id': str(test_storage_location.id),
                'category_id': str(cat.id),
                'metadata': {'something_else': 'free text'},
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text


class TestItemUpdateMetadataValidation:
    """PUT /api/v1/items/{id} must validate meta_data on update too."""

    def test_update_item_with_malformed_money_metadata_rejected(
        self, client, auth_headers, test_storage_location, db_session
    ):
        from app.models.category import Category

        cat = _category_with_money_field(db_session, Category)
        # First create a valid item
        create_resp = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Bottle',
                'quantity': 1,
                'unit': 'bottle',
                'location_id': str(test_storage_location.id),
                'category_id': str(cat.id),
                'metadata': {'deposit_value': {'amount': 0.5, 'currency': 'PLN'}},
            },
        )
        assert create_resp.status_code == status.HTTP_201_CREATED
        item_id = create_resp.json()['id']

        # Now update with a malformed money value
        update_resp = client.put(
            f'/api/v1/items/{item_id}',
            headers=auth_headers,
            json={'metadata': {'deposit_value': 'invalid'}},
        )
        assert update_resp.status_code == status.HTTP_400_BAD_REQUEST, update_resp.text
