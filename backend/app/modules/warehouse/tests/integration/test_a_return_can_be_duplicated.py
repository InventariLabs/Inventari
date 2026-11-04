"""A return is a draft like any other, so it can be copied like any other.

Its reason is a return's own code (NOT_NEEDED is not a scrap reason), which
the create schema of a scrap refused: duplicating a return answered 400.
"""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation

API = '/api/v1/warehouse'


@pytest.mark.integration
def test_a_return_is_duplicated_with_its_reason_and_partner(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
    doc_partner: Partner,
) -> None:
    received = client.post(
        f'{API}/documents',
        headers=doc_auth_headers,
        json={
            'type': 'IN',
            'partner_id': str(doc_partner.id),
            'target_location_id': str(doc_target_location.id),
            'lines': [
                {'product_template_id': str(doc_template.id), 'expected_quantity': '5'}
            ],
        },
    )
    assert received.status_code == status.HTTP_201_CREATED, received.text
    original_id = cast(str, received.json()['id'])
    assert (
        client.patch(
            f'{API}/documents/{original_id}/confirm', headers=doc_auth_headers
        ).status_code
        == status.HTTP_200_OK
    )
    assert (
        client.patch(
            f'{API}/documents/{original_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        ).status_code
        == status.HTTP_200_OK
    )
    returned = client.post(
        f'{API}/documents/{original_id}/return',
        headers=doc_auth_headers,
        json={
            'reason_code': 'NOT_NEEDED',
            'lines': [{'original_line_number': 1, 'return_quantity': '2'}],
        },
    )
    assert returned.status_code == status.HTTP_201_CREATED, returned.text

    copy = client.post(
        f'{API}/documents/{returned.json()["id"]}/duplicate',
        headers=doc_auth_headers,
    )

    assert copy.status_code == status.HTTP_201_CREATED, copy.text
    body = copy.json()
    assert body['reason_code'] == 'NOT_NEEDED'
    assert body['partner_id'] == str(doc_partner.id)
    assert body['status'] == 'DRAFT'
