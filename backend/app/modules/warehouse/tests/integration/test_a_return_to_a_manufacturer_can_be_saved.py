"""A return draft keeps a partner its own form can save.

A return copies the partner from the document it undoes, and a receipt may come
from a manufacturer. The issue that sends the goods back accepted suppliers but
not manufacturers, so the draft existed with a partner that its next save
refused.
"""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation

API = '/api/v1/warehouse'


@pytest.mark.integration
def test_a_return_to_a_manufacturer_saves_with_its_partner(
    client: TestClient,
    db_session: Session,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
    doc_partner: Partner,
) -> None:
    doc_partner.type = 'MANUFACTURER'
    db_session.commit()
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
    posted = client.post(
        f'{API}/documents/{original_id}/post', headers=doc_auth_headers
    )
    assert posted.status_code == status.HTTP_200_OK, posted.text
    returned = client.post(
        f'{API}/documents/{original_id}/return',
        headers=doc_auth_headers,
        json={
            'reason_code': 'NOT_NEEDED',
            'lines': [{'original_line_number': 1, 'return_quantity': '2'}],
        },
    )
    assert returned.status_code == status.HTTP_201_CREATED, returned.text

    saved = client.put(
        f'{API}/documents/{returned.json()["id"]}',
        headers=doc_auth_headers,
        json={'partner_id': str(doc_partner.id)},
    )

    assert saved.status_code == status.HTTP_200_OK, saved.text
    assert saved.json()['partner_id'] == str(doc_partner.id)
