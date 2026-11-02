"""A list asked for receipts and dispatches together returns exactly those.

A work queue shows receipts and dispatches side by side, ordered by one date.
With one type per request it had to merge two pages by hand and could not
say how many documents there were in all.
"""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation


@pytest.mark.integration
class TestTheListTakesSeveralTypes:
    def test_a_comma_separated_type_names_each_of_them(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        for doc_type in ('IN', 'OUT', 'INT'):
            resp = client.post(
                '/api/v1/warehouse/documents',
                headers=doc_auth_headers,
                json={
                    'type': doc_type,
                    'partner_id': str(doc_partner.id),
                    'source_location_id': str(doc_source_location.id),
                    'target_location_id': str(doc_target_location.id),
                    'lines': [
                        {
                            'product_template_id': str(doc_template.id),
                            'expected_quantity': '2',
                        }
                    ],
                },
            )
            assert resp.status_code == status.HTTP_201_CREATED, resp.text

        resp = client.get(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            params={'type': 'IN,OUT'},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        body = resp.json()
        assert sorted(cast(str, d['type']) for d in body['items']) == ['IN', 'OUT']
        assert body['total'] == 2
