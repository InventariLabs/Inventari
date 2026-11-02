"""A product's SKU can be typed when it is added and corrected when it is edited.

The SKU was shown on the list and on the product page and came from a
document, an opening stock or the organization's numbering — no catalogue form
could set it, so a SKU typed wrong on a receipt stayed wrong and a product
added by hand never had one of its own choosing.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.product_template import ProductTemplate

pytestmark = pytest.mark.integration

ITEM_URL = '/api/v1/items'


def _add(client, auth_headers, shelf, **extra):
    response = client.post(
        ITEM_URL,
        headers=auth_headers,
        json={
            'name': 'Hex bolt M8',
            'quantity': 5,
            'location_id': str(shelf.id),
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_sku_typed_on_the_add_form_lands_on_the_product(
    client, auth_headers, test_storage_location
) -> None:
    item = _add(client, auth_headers, test_storage_location, sku=' bolt-m8 ')

    assert item['template']['sku'] == 'BOLT-M8'


def test_the_edit_form_changes_the_sku_and_the_audit_log_says_so(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    item = _add(client, auth_headers, test_storage_location, sku='BOLT-M8')

    response = client.put(
        f'{ITEM_URL}/{item["id"]}', headers=auth_headers, json={'sku': 'BOLT-M8-ZN'}
    )

    assert response.status_code == 200, response.text
    assert response.json()['template']['sku'] == 'BOLT-M8-ZN'
    entries = db_session.scalars(
        select(AuditLog).where(AuditLog.target_id == item['id'])
    ).all()
    updates = [e for e in entries if 'sku' in (e.snapshot or {}).get('fields', [])]
    assert len(updates) == 1
    assert updates[0].snapshot['before']['sku'] == 'BOLT-M8'
    assert updates[0].snapshot['after']['sku'] == 'BOLT-M8-ZN'


def test_a_blank_sku_on_the_edit_form_clears_it(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    item = _add(client, auth_headers, test_storage_location, sku='BOLT-M8')

    response = client.put(
        f'{ITEM_URL}/{item["id"]}', headers=auth_headers, json={'sku': '  '}
    )

    assert response.status_code == 200, response.text
    assert response.json()['template']['sku'] is None


def test_a_sku_another_product_carries_is_refused_by_name(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    _add(client, auth_headers, test_storage_location, sku='BOLT-M8')
    other = client.post(
        ITEM_URL,
        headers=auth_headers,
        json={
            'name': 'Hex nut M8',
            'quantity': 5,
            'location_id': str(test_storage_location.id),
        },
    ).json()

    response = client.put(
        f'{ITEM_URL}/{other["id"]}', headers=auth_headers, json={'sku': 'BOLT-M8'}
    )

    assert response.status_code == 400, response.text
    assert 'BOLT-M8' in response.text
    taken = db_session.scalars(
        select(ProductTemplate).where(ProductTemplate.sku == 'BOLT-M8')
    ).all()
    assert len(taken) == 1


def test_a_sku_that_is_not_a_sku_is_refused(
    client, auth_headers, test_storage_location
) -> None:
    response = client.post(
        ITEM_URL,
        headers=auth_headers,
        json={
            'name': 'Hex bolt M8',
            'quantity': 5,
            'location_id': str(test_storage_location.id),
            'sku': 'no spaces allowed',
        },
    )

    assert response.status_code in (400, 422), response.text
