"""Completing a document without saying what arrived is not a delivery.

A completion that carries no per-line answers used to book every line nobody
answered for as delivered in full. The execution panel names every line and a
scanning session resolves each one before it closes, so only an integration, a
script or a webhook consumer ever sent such a request — and its documents
posted stock that never arrived. The request now has to say so
(``complete_as_planned``); without it the answer names the lines.

A body that answers only some of the lines is the same request through a
narrower door: the lines it leaves out have no answer and are refused just the
same, unless the flag says the caller means them as planned.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation

# A receipt takes only products on the list into stock: both goods are
# products, named by their codes.
_OATS = '5901234560033'
_RICE = '5901234560040'


@pytest.fixture(autouse=True)
def _the_goods_are_on_the_list(h: ModuleTestHelper, doc_org: Organization) -> None:
    h.create_template(doc_org, name='Bodiless Oats', barcode=_OATS)
    h.create_template(doc_org, name='Bodiless Rice', barcode=_RICE)


def _confirmed_receipt(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    shelf: StorageLocation,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(shelf.id),
            'lines': [
                {'name': 'Bodiless Oats', 'barcode': _OATS, 'expected_quantity': 5},
                {'name': 'Bodiless Rice', 'barcode': _RICE, 'expected_quantity': 7},
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    return doc_id


@pytest.mark.integration
class TestABodilessCompletionNamesTheUnansweredLines:
    @pytest.mark.parametrize('body', [None, {}, {'unit_confirmed_over_template': True}])
    def test_the_completion_is_refused_and_books_nothing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        body: dict[str, object] | None,
    ) -> None:
        doc_id = _confirmed_receipt(
            client, doc_auth_headers, doc_partner, doc_target_location
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json=body,
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert '1, 2' in resp.text and 'complete_as_planned' in resp.text
        doc = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()
        assert doc['status'] == 'CONFIRMED'

    def test_a_body_that_names_one_of_two_lines_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc_id = _confirmed_receipt(
            client, doc_auth_headers, doc_partner, doc_target_location
        )
        lines = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()['lines']
        answered = next(line for line in lines if line['line_number'] == 1)

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': answered['id'],
                        'done_quantity': answered['expected_quantity'],
                    }
                ]
            },
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'Unanswered lines: 2' in resp.text
        assert 'complete_as_planned' in resp.text
        doc = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()
        assert doc['status'] == 'CONFIRMED'
        assert {Decimal(str(line['done_quantity'])) for line in doc['lines']} == {
            Decimal('0')
        }

    def test_the_flag_covers_the_line_the_body_leaves_out(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc_id = _confirmed_receipt(
            client, doc_auth_headers, doc_partner, doc_target_location
        )
        lines = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()['lines']
        answered = next(line for line in lines if line['line_number'] == 1)

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': answered['id'],
                        'done_quantity': answered['expected_quantity'],
                    }
                ],
                'complete_as_planned': True,
            },
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'COMPLETED'
        done = sorted(Decimal(str(ln['done_quantity'])) for ln in resp.json()['lines'])
        assert done == [Decimal('5'), Decimal('7')]

    def test_the_flag_books_every_line_as_planned(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
    ) -> None:
        doc_id = _confirmed_receipt(
            client, doc_auth_headers, doc_partner, doc_target_location
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'COMPLETED'
        done = sorted(Decimal(str(ln['done_quantity'])) for ln in resp.json()['lines'])
        assert done == [Decimal('5'), Decimal('7')]
