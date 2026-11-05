"""The answer to a transition names the person who made it.

The screens read the document again after every action, so a name missing from
the immediate answer never showed there; an API client reading that answer got
``confirmed_by`` with ``confirmed_by_name: null`` — the id of somebody the
document would not name. The relationship behind the name is loaded with the
row, while the stamp is still empty, and setting the stamp does not reload it.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation


def _draft(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    location: StorageLocation,
    template: ProductTemplate,
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(location.id),
            'lines': [
                {'product_template_id': str(template.id), 'expected_quantity': '1'}
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, Any], resp.json())


@pytest.mark.integration
class TestATransitionAnswersWithWhoMadeIt:
    def test_confirming_names_the_confirmer(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        draft = _draft(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{draft["id"]}/confirm',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['confirmed_by'] is not None
        assert resp.json()['confirmed_by_name']

    def test_completing_names_the_completer_and_the_confirmer(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        draft = _draft(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{draft["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

        resp = client.patch(
            f'/api/v1/warehouse/documents/{draft["id"]}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['completed_by_name']
        assert resp.json()['confirmed_by_name']

    def test_posting_in_one_step_names_both_hands(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        draft = _draft(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{draft["id"]}/post',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['completed_by_name']
        assert resp.json()['confirmed_by_name']
