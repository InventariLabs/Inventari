"""A list search reaches the products on a document's lines.

A person looking for a movement rarely remembers its number; they remember
what moved. The search accepted the number, the notes and the partner, and
answered "Gouda" with nothing over a shelf of receipts that all carried it.
The status filter takes several statuses at once, so that "drafts and planned
work" is one list rather than two merged by hand.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation


def _receipt(
    client: TestClient,
    headers: dict[str, str],
    *,
    target_location_id: uuid.UUID,
    template_id: uuid.UUID,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'target_location_id': str(target_location_id),
            'lines': [
                {'product_template_id': str(template_id), 'expected_quantity': 1}
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    doc_id: str = resp.json()['id']
    return doc_id


def _list(client: TestClient, headers: dict[str, str], **params: str) -> set[str]:
    resp = client.get('/api/v1/warehouse/documents', headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return {d['id'] for d in resp.json()['items']}


@pytest.mark.integration
class TestSearchFindsTheProduct:
    def test_a_product_name_finds_the_documents_that_carry_it(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        gouda = h.create_template(doc_org, name='Gouda Cheese')
        butter = h.create_template(doc_org, name='Butter 200g')
        with_gouda = _receipt(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            template_id=gouda.id,
        )
        with_butter = _receipt(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            template_id=butter.id,
        )

        found = _list(client, doc_auth_headers, search='gouda')
        assert with_gouda in found
        assert with_butter not in found

    def test_a_document_with_two_matching_lines_is_listed_once(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        a = h.create_template(doc_org, name='Gouda young')
        b = h.create_template(doc_org, name='Gouda aged')
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {'product_template_id': str(a.id), 'expected_quantity': 1},
                    {'product_template_id': str(b.id), 'expected_quantity': 1},
                ],
            },
        )
        assert resp.status_code == 201, resp.text

        listed = client.get(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            params={'search': 'gouda'},
        ).json()
        assert listed['total'] == 1
        assert len(listed['items']) == 1


@pytest.mark.integration
class TestTheListTakesSeveralStatuses:
    def test_a_comma_separated_status_names_each_of_them(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        draft = _receipt(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            template_id=doc_template.id,
        )
        confirmed = _receipt(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            template_id=doc_template.id,
        )
        resp = client.patch(
            f'/api/v1/warehouse/documents/{confirmed}/confirm', headers=doc_auth_headers
        )
        assert resp.status_code == 200, resp.text
        cancelled = _receipt(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            template_id=doc_template.id,
        )
        resp = client.patch(
            f'/api/v1/warehouse/documents/{cancelled}/cancel', headers=doc_auth_headers
        )
        assert resp.status_code == 200, resp.text

        found = _list(client, doc_auth_headers, status='DRAFT,CONFIRMED')
        assert found == {draft, confirmed}
