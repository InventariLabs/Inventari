"""A code typed into the edit form is the product's, as on creation.

A receiving or picking scan looks a code up on ``product_templates.barcode``
and nowhere else. Creation already offers a code to the record's catalogue
row; the edit form wrote it onto the record's own column, where no scan
reads it — so a worker who gave a product its code from the form still met
"product not recognized" at the terminal.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import status
from sqlalchemy import select

pytestmark = pytest.mark.integration


def _barcode() -> str:
    return f'EDT-{uuid.uuid4().hex[:12]}'


def _create(client, auth_headers, storage_id, **overrides):
    payload = {
        'name': f'Patch cable {uuid.uuid4().hex[:6]}',
        'quantity': 1,
        'location_id': str(storage_id),
    }
    payload.update(overrides)
    response = client.post('/api/v1/items', headers=auth_headers, json=payload)
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return response.json()


def _edit(client, auth_headers, item_id, **fields):
    return client.put(f'/api/v1/items/{item_id}', headers=auth_headers, json=fields)


def test_a_code_given_in_the_edit_form_is_where_a_scan_reads_it(
    client, auth_headers, test_storage_location, db_session
):
    from app.models.item import Item
    from app.models.product_template import ProductTemplate

    record = _create(client, auth_headers, test_storage_location.id)
    code = _barcode()

    response = _edit(client, auth_headers, record['id'], barcode=code)

    assert response.status_code == status.HTTP_200_OK, response.text
    template = db_session.get(ProductTemplate, uuid.UUID(record['template_id']))
    db_session.refresh(template)
    assert template.barcode == code
    item = db_session.get(Item, uuid.UUID(record['id']))
    db_session.refresh(item)
    assert item.barcode is None


def test_saving_the_products_own_code_back_is_no_change(
    client, auth_headers, test_storage_location, db_session
):
    """The form shows the product's code and posts its whole state, so the
    second record of a product sends that code back on every save. It must
    not land on the record, where it would refuse the next record's save."""
    from app.models.item import Item

    code = _barcode()
    first = _create(client, auth_headers, test_storage_location.id, barcode=code)
    second = _create(
        client,
        auth_headers,
        test_storage_location.id,
        name=first['name'],
        barcode=code,
    )

    for record in (first, second):
        response = _edit(client, auth_headers, record['id'], barcode=code)
        assert response.status_code == status.HTTP_200_OK, response.text

    holders = db_session.scalars(select(Item).where(Item.barcode == code)).all()
    assert holders == []


def test_a_code_another_product_carries_refuses_with_the_sentence(
    client, auth_headers, test_storage_location, db_session
):
    from app.models.product_template import ProductTemplate

    code = _barcode()
    _create(client, auth_headers, test_storage_location.id, barcode=code)
    other = _create(client, auth_headers, test_storage_location.id)

    response = _edit(client, auth_headers, other['id'], barcode=code)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
    detail = response.json()['detail']
    message = detail['message'] if isinstance(detail, dict) else str(detail)
    assert f'Barcode already in use: {code}' in message
    template = db_session.get(ProductTemplate, uuid.UUID(other['template_id']))
    db_session.refresh(template)
    assert template.barcode is None


def test_emptying_the_code_takes_it_off_the_product(
    client, auth_headers, test_storage_location, db_session
):
    """The form shows the product's code, so clearing the field must clear
    it there — not report success and show the old code on the next load."""
    from app.models.product_template import ProductTemplate

    code = _barcode()
    record = _create(client, auth_headers, test_storage_location.id, barcode=code)
    template = db_session.get(ProductTemplate, uuid.UUID(record['template_id']))
    db_session.refresh(template)
    assert template.barcode == code

    response = _edit(client, auth_headers, record['id'], barcode=None)

    assert response.status_code == status.HTTP_200_OK, response.text
    db_session.refresh(template)
    assert template.barcode is None
    assert response.json()['template']['barcode'] is None
