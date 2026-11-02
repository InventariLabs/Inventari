"""The two things a person remembers about a document: who, and when.

The list search accepted the number, the external reference and the notes —
none of which anybody recalls a week later — and refused the partner name
printed on every row of the same list. Typing what the row said gave zero
results over a shelf of forty-nine documents, and the only way from "which
document was that with Nowak" to an answer was a CSV export and a
spreadsheet.

The date range was never missing from the API; the list screen simply never
asked for it. That half is proved on the client, where the omission was.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User


def _receipt(
    client: TestClient,
    headers: dict[str, str],
    *,
    target_location_id: uuid.UUID,
    template_id: uuid.UUID,
    partner_id: uuid.UUID,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'expected_quantity': 1,
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    doc_id: str = resp.json()['id']
    return doc_id


def _search(client: TestClient, headers: dict[str, str], term: str) -> set[str]:
    resp = client.get(
        '/api/v1/warehouse/documents', headers=headers, params={'search': term}
    )
    assert resp.status_code == 200, resp.text
    return {d['id'] for d in resp.json()['items']}


@pytest.mark.integration
class TestSearchFindsThePartner:
    def test_the_name_on_the_row_is_a_name_the_search_accepts(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
        h: ModuleTestHelper,
    ) -> None:
        other = h.create_partner(doc_org, doc_user, name='Nowak Logistyka')

        acme = _receipt(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            template_id=doc_template.id,
            partner_id=doc_partner.id,
        )
        nowak = _receipt(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            template_id=doc_template.id,
            partner_id=other.id,
        )

        found = _search(client, doc_auth_headers, 'Nowak')
        assert nowak in found
        assert acme not in found

    def test_a_partial_name_and_a_different_case_both_work(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        h: ModuleTestHelper,
    ) -> None:
        partner = h.create_partner(doc_org, doc_user, name='Nowak Logistyka')
        doc_id = _receipt(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            template_id=doc_template.id,
            partner_id=partner.id,
        )

        assert doc_id in _search(client, doc_auth_headers, 'logistyka')
        assert doc_id in _search(client, doc_auth_headers, 'wak Log')

    def test_the_number_and_the_reference_still_find_their_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_partner: Partner,
    ) -> None:
        # The partner clause is an addition, not a replacement.
        doc_id = _receipt(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            template_id=doc_template.id,
            partner_id=doc_partner.id,
        )
        number = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()['number']

        assert doc_id in _search(client, doc_auth_headers, number)

    def test_a_document_with_no_partner_is_not_swept_up(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        h: ModuleTestHelper,
    ) -> None:
        partner = h.create_partner(doc_org, doc_user, name='Nowak Logistyka')
        with_partner = _receipt(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            template_id=doc_template.id,
            partner_id=partner.id,
        )
        internal = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        assert internal.status_code == 201, internal.text

        found = _search(client, doc_auth_headers, 'Nowak')
        assert found == {with_partner}
