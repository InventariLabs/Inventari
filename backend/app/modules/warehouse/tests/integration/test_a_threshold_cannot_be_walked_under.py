"""A value nobody stated is not a value below the threshold.

Two ways past a configured approval threshold, both quiet.

A document with no prices on it had ``total_net`` of NULL, which the
threshold read as zero — so the one document whose worth nobody had written
down passed under every limit. Zero and unknown are not the same answer, and
this codebase already refuses to confuse them where the cost layers are
concerned.

And the gate opened when the workflow went away. Confirmation refuses a
document that needs an approval nobody can run, naming the missing workflow;
completion asked the approvals module, which treats "no workflow" as nothing
to enforce — reasonable when nobody asked for a control, wrong when the
document in front of it is under one.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.approvals.models import ApprovalWorkflow


def _set_threshold(
    client: TestClient, headers: dict[str, str], threshold: str | None
) -> None:
    profile = client.get('/api/v1/warehouse/profile', headers=headers).json()
    resp = client.put(
        '/api/v1/warehouse/profile',
        headers=headers,
        json={
            **{
                k: v
                for k, v in profile.items()
                if k not in ('id', 'organization_id', 'created_at', 'updated_at')
            },
            'approval_threshold': threshold,
            'approval_required_for_types': [],
            'value_tracking_enabled': True,
        },
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


def _receipt(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    location_id: Any,
    template_id: Any,
    unit_price: str | None,
) -> str:
    line: dict[str, Any] = {
        'product_template_id': str(template_id),
        'expected_quantity': '10',
    }
    if unit_price is not None:
        line['unit_price'] = unit_price
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'lines': [line],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


@pytest.mark.integration
class TestAValueNobodyStatedIsNotBelowTheThreshold:
    def test_a_document_with_no_prices_needs_the_approval(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_approval_workflow: ApprovalWorkflow,
    ) -> None:
        _set_threshold(client, doc_auth_headers, '100.00')
        doc_id = _receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            unit_price=None,
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        assert confirm.json()['status'] == 'PENDING_APPROVAL', confirm.json()

    def test_a_document_priced_at_zero_does_not(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """The control: somebody said zero, and zero is under a hundred.

        No workflow here: the profile names a threshold, so that threshold is
        the whole rule — an active workflow would carry it out, not widen
        it.
        """
        _set_threshold(client, doc_auth_headers, '100.00')
        doc_id = _receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            unit_price='0.00',
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        assert confirm.json()['status'] == 'CONFIRMED', confirm.json()


@pytest.mark.integration
class TestTheGateDoesNotOpenWhenTheWorkflowGoesAway:
    def test_completion_refuses_when_the_control_cannot_be_run(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """Confirmed under a high limit, completed under a low one."""
        _set_threshold(client, doc_auth_headers, '10000.00')
        doc_id = _receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            unit_price='50.00',
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        assert confirm.json()['status'] == 'CONFIRMED', confirm.json()

        _set_threshold(client, doc_auth_headers, '100.00')
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_403_FORBIDDEN,
            status.HTTP_409_CONFLICT,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        ), done.text

    def test_an_approval_already_given_survives_the_workflow_going_away(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_approval_workflow: ApprovalWorkflow,
    ) -> None:
        """Approved, then the workflow is switched off: the approval stands.

        The gate refuses a control it cannot run; it does not take back one
        that has been run. Taking the workflow away after the fact is not a
        reason to hold a document its approver already let through.
        """
        _set_threshold(client, doc_auth_headers, '100.00')
        doc_id = _receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            unit_price='50.00',
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        assert confirm.json()['status'] == 'PENDING_APPROVAL', confirm.json()
        approve = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=doc_auth_headers
        )
        assert approve.status_code == status.HTTP_200_OK, approve.text

        off = client.patch(
            f'/api/v1/approvals/workflows/{doc_approval_workflow.id}',
            headers=doc_auth_headers,
            json={'is_active': False},
        )
        assert off.status_code == status.HTTP_200_OK, off.text

        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text

    def test_a_document_under_the_limit_still_completes(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """The control: no control asked for, nothing to enforce."""
        _set_threshold(client, doc_auth_headers, '10000.00')
        doc_id = _receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            unit_price='50.00',
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text
