"""
A product's unit weight and volume land in numeric(14, 6) columns of
``product_templates``. Every request that writes them refuses a value the
column cannot hold, and a negative one, with a 422 naming the field and the
bound.
"""

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.product_template import ProductTemplate

#: Past the column on one side, below nothing on the other. 1e8 is the first
#: magnitude numeric(14, 6) cannot hold.
REFUSED = [(1e30, 'less_than_equal'), (1e8, 'less_than_equal')]
REFUSED.append((-5, 'greater_than_equal'))


def _assert_refused(response: Any, field: str, error_type: str) -> None:
    assert response.status_code == 422, response.text
    error = response.json()['detail'][0]
    assert error['loc'][-1] == field
    assert error['type'] == error_type


@pytest.mark.integration
@pytest.mark.parametrize(('value', 'error_type'), REFUSED)
@pytest.mark.parametrize('field', ['weight_value', 'volume_value'])
class TestAMeasureTheColumnCannotHold:
    def test_the_product_door_refuses_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        field: str,
        value: float,
        error_type: str,
    ) -> None:
        response = client.post(
            '/api/v1/items/product-templates',
            headers=auth_headers,
            json={'name': 'Oversized tin', field: value},
        )

        _assert_refused(response, field, error_type)
        assert (
            db_session.query(ProductTemplate).filter_by(name='Oversized tin').count()
            == 0
        )

    def test_the_item_door_refuses_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: Any,
        field: str,
        value: float,
        error_type: str,
    ) -> None:
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Oversized tin',
                'location_id': str(test_storage_location.id),
                field: value,
            },
        )

        _assert_refused(response, field, error_type)
        assert db_session.query(Item).filter_by(name='Oversized tin').count() == 0


@pytest.mark.integration
@pytest.mark.parametrize(('value', 'error_type'), REFUSED)
def test_the_quick_add_after_a_scan_refuses_a_weight_the_column_cannot_hold(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_storage_location: Any,
    value: float,
    error_type: str,
) -> None:
    response = client.post(
        '/api/v1/labels/scan/5901234123457/assign',
        headers=auth_headers,
        json={
            'name': 'Oversized tin',
            'location_id': str(test_storage_location.id),
            'weight_value': value,
        },
    )

    _assert_refused(response, 'weight_value', error_type)
    assert db_session.query(Item).filter_by(name='Oversized tin').count() == 0


@pytest.mark.integration
@pytest.mark.parametrize('value', [0, 99_999_999])
def test_the_ends_of_the_range_are_stored(
    client: TestClient,
    auth_headers: dict[str, str],
    value: int,
) -> None:
    response = client.post(
        '/api/v1/items/product-templates',
        headers=auth_headers,
        json={'name': 'Edge tin', 'weight_value': value, 'volume_value': value},
    )

    assert response.status_code == 201, response.text
    assert response.json()['weight_value'] == value
    assert response.json()['volume_value'] == value


@pytest.mark.integration
def test_a_product_already_stored_with_a_negative_measure_is_still_read(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    """The bound is on what a request writes: a row is answered as stored."""
    created = client.post(
        '/api/v1/items/product-templates',
        headers=auth_headers,
        json={'name': 'Old tin'},
    ).json()
    template = db_session.get(ProductTemplate, UUID(created['id']))
    assert template is not None
    template.weight_value = -5
    template.volume_value = -5
    db_session.commit()

    response = client.get(
        f'/api/v1/items/product-templates/{created["id"]}', headers=auth_headers
    )

    assert response.status_code == 200, response.text
    assert response.json()['weight_value'] == -5
    assert response.json()['volume_value'] == -5
