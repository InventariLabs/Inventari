"""A list row names the shelves its document goes between.

The list screen and the To do queue both draw a location line from
``source_location_name``/``target_location_name``. The plain list built its
rows with ``DocumentSchema.model_validate``, which leaves those two fields
``None`` — they are read from a relation, not stored on the document — while
``list_documents`` already eager-loads both shelves. The line therefore never
appeared on a list row, and only the approvals queue filled the names in by
hand.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration


def _create(
    client: TestClient,
    headers: dict[str, str],
    *,
    doc_type: str,
    partner: Partner,
    template: ProductTemplate,
    source: StorageLocation | None = None,
    target: StorageLocation | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'type': doc_type,
        'partner_id': str(partner.id),
        'lines': [{'product_template_id': str(template.id), 'expected_quantity': '2'}],
    }
    if source is not None:
        payload['source_location_id'] = str(source.id)
    if target is not None:
        payload['target_location_id'] = str(target.id)
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=payload)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    created: dict[str, Any] = resp.json()
    return created


class TestTheListRowNamesItsShelves:
    def test_an_internal_transfer_names_both_shelves_on_the_list(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        created = _create(
            client,
            doc_auth_headers,
            doc_type='INT',
            partner=doc_partner,
            template=doc_template,
            source=doc_source_location,
            target=doc_target_location,
        )

        listed = client.get('/api/v1/warehouse/documents', headers=doc_auth_headers)
        assert listed.status_code == status.HTTP_200_OK, listed.text
        (row,) = [d for d in listed.json()['items'] if d['id'] == created['id']]

        assert row['source_location_name'] == doc_source_location.name
        assert row['target_location_name'] == doc_target_location.name

    def test_a_receipt_names_the_shelf_it_goes_to_and_leaves_the_other_empty(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        created = _create(
            client,
            doc_auth_headers,
            doc_type='IN',
            partner=doc_partner,
            template=doc_template,
            target=doc_target_location,
        )

        listed = client.get(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            params={'type': 'IN'},
        )
        assert listed.status_code == status.HTTP_200_OK, listed.text
        (row,) = [d for d in listed.json()['items'] if d['id'] == created['id']]

        assert row['source_location_name'] is None
        assert row['target_location_name'] == doc_target_location.name
