"""A surplus is recorded where it is noticed, within one rule.

The defect: a receiving session refused anything above the expected
quantity, while a correction of the same closed receipt accepted any
amount an hour later. The rule now lives in one place. Within the
organization's over-receipt tolerance anyone who may receive records the
surplus; past it only a holder of ``warehouse:receive_over_tolerance``.
Every surplus line names why (SURPLUS by default), the same way a short
line names SHORTAGE.

These tests hold the no-order side: the ramp, the completion body and a
correction with no order line to weigh against. The order-linked side
lives with the purchase orders tests, where the event subscription that
recomputes ``quantity_received`` is wired.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import DocumentLine


def _receiver_headers(
    h: ModuleTestHelper,
    org: Organization,
    *,
    may_exceed: bool,
    email: str,
) -> dict[str, str]:
    """A receiving user, with or without the over-receipt permission."""
    user = h.create_user(org, email=email, role='user')
    permissions = ['warehouse:read', 'warehouse:write']
    if may_exceed:
        permissions.append('warehouse:receive_over_tolerance')
    h.grant_permissions(user, permissions)
    return h.get_auth_headers(user)


def _create_in_document(
    client: TestClient,
    headers: dict[str, str],
    *,
    target_location_id: Any,
    partner_id: Any,
    template_id: Any,
    quantity: str,
) -> dict[str, Any]:
    response = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                }
            ],
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return cast(dict[str, Any], response.json())


def _confirm(client: TestClient, headers: dict[str, str], doc_id: str) -> None:
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


def _document_line(db_session: Session, doc_id: str) -> DocumentLine:
    from uuid import UUID

    line = (
        db_session.query(DocumentLine)
        .filter(DocumentLine.document_id == UUID(doc_id))
        .one()
    )
    return line


def _start_receiving(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> dict[str, Any]:
    start = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/start', headers=headers
    )
    assert start.status_code == status.HTTP_201_CREATED, start.text
    return cast(dict[str, Any], start.json())


@pytest.mark.integration
class TestTheRampAcceptsASurplus:
    def test_within_tolerance_any_receiver_records_it(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        h.set_module_settings(
            doc_org, 'warehouse', {'over_receipt_tolerance_percent': 10}
        )
        receiver = _receiver_headers(
            h, doc_org, may_exceed=False, email='tolerance@example.com'
        )
        doc = _create_in_document(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity='3',
        )
        _confirm(client, doc_auth_headers, doc['id'])
        session = _start_receiving(client, receiver, doc['id'])

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/receiving/{session["id"]}/short-receive',
            headers=receiver,
            json={
                'line_id': session['lines'][0]['id'],
                'received_quantity': '3.3',
            },
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['received_quantity'] == pytest.approx(3.3)

        db_session.expire_all()
        line = _document_line(db_session, doc['id'])
        assert line.done_quantity == Decimal('3.3')
        assert line.discrepancy_code == 'SURPLUS', (
            'a surplus line names why, like a short one'
        )

    def test_past_tolerance_without_the_permission_is_refused(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        h.set_module_settings(
            doc_org, 'warehouse', {'over_receipt_tolerance_percent': 10}
        )
        receiver = _receiver_headers(
            h, doc_org, may_exceed=False, email='refused@example.com'
        )
        doc = _create_in_document(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity='3',
        )
        _confirm(client, doc_auth_headers, doc['id'])
        session = _start_receiving(client, receiver, doc['id'])

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/receiving/{session["id"]}/short-receive',
            headers=receiver,
            json={
                'line_id': session['lines'][0]['id'],
                'received_quantity': '4',
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'over-receipt tolerance' in resp.text
        assert 'receive over tolerance' in resp.text

    def test_past_tolerance_the_holder_is_asked_then_it_is_recorded(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The permission lifts the tolerance, but the count is asked about.

        The holder used to record any surplus on the spot. The session now
        answers 409 with a question naming the product and the surplus,
        records nothing, and records the count once it is sent with the
        answer.
        """
        h.set_module_settings(
            doc_org, 'warehouse', {'over_receipt_tolerance_percent': 10}
        )
        receiver = _receiver_headers(
            h, doc_org, may_exceed=True, email='allowed@example.com'
        )
        doc = _create_in_document(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity='3',
        )
        _confirm(client, doc_auth_headers, doc['id'])
        session = _start_receiving(client, receiver, doc['id'])
        url = (
            f'/api/v1/warehouse/documents/{doc["id"]}/receiving/'
            f'{session["id"]}/short-receive'
        )
        body = {'line_id': session['lines'][0]['id'], 'received_quantity': '4'}

        asked = client.post(url, headers=receiver, json=body)
        assert asked.status_code == status.HTTP_409_CONFLICT, asked.text
        assert asked.json()['detail']['code'] == 'SURPLUS_NEEDS_CONFIRMATION'
        assert asked.json()['detail']['message'] == (
            f'{doc_template.name}: receiving 4 is 1 more than the 3 expected. '
            'Receive the surplus?'
        )
        db_session.expire_all()
        assert _document_line(db_session, doc['id']).done_quantity == Decimal('0')

        resp = client.post(
            url, headers=receiver, json=body, params={'confirm_surplus': 'true'}
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.expire_all()
        line = _document_line(db_session, doc['id'])
        assert line.done_quantity == Decimal('4')
        assert line.discrepancy_code == 'SURPLUS'

    def test_past_the_ceiling_even_the_holder_is_refused(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        h.set_module_settings(
            doc_org,
            'warehouse',
            {'over_receipt_tolerance_percent': 10, 'over_receipt_ceiling_percent': 50},
        )
        receiver = _receiver_headers(
            h, doc_org, may_exceed=True, email='ceiling@example.com'
        )
        doc = _create_in_document(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity='4',
        )
        _confirm(client, doc_auth_headers, doc['id'])
        session = _start_receiving(client, receiver, doc['id'])
        url = (
            f'/api/v1/warehouse/documents/{doc["id"]}/receiving/'
            f'{session["id"]}/short-receive'
        )

        # Six of four is the ceiling itself; seven is past it.
        refused = client.post(
            url,
            headers=receiver,
            json={'line_id': session['lines'][0]['id'], 'received_quantity': '7'},
            params={'confirm_surplus': 'true'},
        )
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert '50% over-receipt ceiling' in refused.text
        db_session.expire_all()
        assert _document_line(db_session, doc['id']).done_quantity == Decimal('0')

        at_ceiling = client.post(
            url,
            headers=receiver,
            json={'line_id': session['lines'][0]['id'], 'received_quantity': '6'},
            params={'confirm_surplus': 'true'},
        )
        assert at_ceiling.status_code == status.HTTP_200_OK, at_ceiling.text


@pytest.mark.integration
class TestCompletionWeighsAnExplicitSurplus:
    def test_a_surplus_past_tolerance_needs_the_permission(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        receiver = _receiver_headers(
            h, doc_org, may_exceed=False, email='complete-refused@example.com'
        )
        doc = _create_in_document(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity='3',
        )
        _confirm(client, doc_auth_headers, doc['id'])
        line_id = doc['lines'][0]['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/complete',
            headers=receiver,
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': '4',
                        'discrepancy_code': 'SURPLUS',
                    }
                ]
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'over-receipt tolerance' in resp.text

    def test_a_surplus_with_the_permission_completes_and_keeps_its_reason(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        receiver = _receiver_headers(
            h, doc_org, may_exceed=True, email='complete-allowed@example.com'
        )
        doc = _create_in_document(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity='3',
        )
        _confirm(client, doc_auth_headers, doc['id'])
        line_id = doc['lines'][0]['id']

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/complete',
            headers=receiver,
            json={'lines': [{'line_id': line_id, 'done_quantity': '4'}]},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.expire_all()
        line = _document_line(db_session, doc['id'])
        assert line.done_quantity == Decimal('4')
        assert line.discrepancy_code == 'SURPLUS', (
            'the reason survives completion, like a shortage'
        )


@pytest.mark.integration
class TestAPositiveCorrectionPassesTheSameGate:
    def _completed_receipt(
        self,
        client: TestClient,
        headers: dict[str, str],
        *,
        target_location_id: Any,
        partner_id: Any,
        template_id: Any,
        quantity: str,
    ) -> dict[str, Any]:
        doc = _create_in_document(
            client,
            headers,
            target_location_id=target_location_id,
            partner_id=partner_id,
            template_id=template_id,
            quantity=quantity,
        )
        _confirm(client, headers, doc['id'])
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text
        return doc

    def _ask_to_correct(
        self,
        client: TestClient,
        headers: dict[str, str],
        *,
        original: dict[str, Any],
        delta: str,
    ) -> Any:
        return client.post(
            '/api/v1/warehouse/corrections',
            headers=headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': delta}],
            },
        )

    def test_a_surplus_correction_without_the_permission_is_refused(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        receiver = _receiver_headers(
            h, doc_org, may_exceed=False, email='correction-refused@example.com'
        )
        receipt = self._completed_receipt(
            client,
            receiver,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity='10',
        )

        resp = self._ask_to_correct(client, receiver, original=receipt, delta='2')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'over-receipt tolerance' in resp.text

    def test_a_surplus_correction_with_the_permission_is_accepted(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        receiver = _receiver_headers(
            h, doc_org, may_exceed=True, email='correction-allowed@example.com'
        )
        receipt = self._completed_receipt(
            client,
            receiver,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity='10',
        )

        resp = self._ask_to_correct(client, receiver, original=receipt, delta='2')
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

    def test_a_short_receipt_can_be_corrected_up_to_expectation_by_anyone(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Eight of ten, corrected by two: the line lands on its expectation."""
        receiver = _receiver_headers(
            h, doc_org, may_exceed=False, email='correction-to-full@example.com'
        )
        doc = _create_in_document(
            client,
            receiver,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity='10',
        )
        _confirm(client, receiver, doc['id'])
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/complete',
            headers=receiver,
            json={
                'lines': [
                    {
                        'line_id': doc['lines'][0]['id'],
                        'done_quantity': '8',
                        'discrepancy_code': 'SHORTAGE',
                    }
                ]
            },
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

        resp = self._ask_to_correct(client, receiver, original=doc, delta='2')
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
