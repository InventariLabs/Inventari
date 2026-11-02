"""The dialog behind the confirm button says when nobody could decide the request.

Confirming a document under a workflow raises the approval request, and the
document parks on the first stage it cannot walk past. When nobody can decide
that stage, the sentence the dialog used to show — "it will go to the approval
queue" — promised a queue the request would never reach: the document sat in
PENDING_APPROVAL and looked like something waiting its turn. The requirement
endpoint now carries the same verdict the parked request would carry, so the
page can say it before the click.
"""

import uuid
from typing import Any, cast

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.models import DocumentStatus
from app.modules.warehouse.tests.integration.test_one_definition_of_approval_required import (
    _create_in,
)


def _workflow(
    client: TestClient, headers: dict[str, str], stages: list[dict[str, object]]
) -> None:
    resp = client.post(
        '/api/v1/approvals/workflows',
        headers=headers,
        json={
            'target_type': 'document',
            'requester_scope': {'everyone': True},
            'name': 'Documents',
            'stages': stages,
            'is_active': True,
            'expected_scope': {'holds': 'all'},
            'allow_undecidable_stages': True,
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text


def _draft(
    client: TestClient,
    headers: dict[str, str],
    location: StorageLocation,
    partner: Partner,
    template: ProductTemplate,
) -> str:
    return _create_in(client, headers, location.id, partner.id, template.id)


def _requirement(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> dict[str, Any]:
    told = client.get(
        f'/api/v1/approvals/documents/{doc_id}/approval-requirement', headers=headers
    )
    assert told.status_code == status.HTTP_200_OK, told.text
    return cast(dict[str, Any], told.json())


@pytest.mark.integration
class TestTheConfirmDialogKnowsADeadEnd:
    def test_a_stage_naming_people_without_access_is_called_a_dead_end(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        blind = h.create_user(doc_org, email='blind@example.com', role='user')
        _workflow(
            client,
            doc_auth_headers,
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Peer review',
                    'approver_user_ids': [str(blind.id)],
                }
            ],
        )
        doc_id = _draft(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )

        told = _requirement(client, doc_auth_headers, doc_id)

        assert told['approval_required'] is True
        assert told['approval_solvable'] is False
        assert told['undecidable_reason'] == 'named_approvers_cannot_decide'
        assert told['undecidable_stage'] == 'Peer review'
        # The verdict is a promise about what confirming does, so confirming
        # does exactly that: it parks the document.
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.json()['status'] == DocumentStatus.PENDING_APPROVAL.value

    def test_the_only_holder_of_the_grant_asking_is_called_a_dead_end(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        # A solo organization: the one person who can approve is the one who
        # asks, and the door refuses a self-decision unless the organization
        # opted in.
        h.set_module_settings(doc_org, 'approvals', {'allow_admin_self_approve': False})
        _workflow(
            client,
            doc_auth_headers,
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager Approval',
                    'approver_user_ids': [],
                }
            ],
        )
        doc_id = _draft(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )

        told = _requirement(client, doc_auth_headers, doc_id)

        assert told['approval_solvable'] is False
        assert told['undecidable_reason'] == 'only_the_requester_can_decide'
        assert told['undecidable_stage'] == 'Manager Approval'

    def test_a_second_holder_of_the_grant_makes_the_same_stage_decidable(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        h.set_module_settings(doc_org, 'approvals', {'allow_admin_self_approve': False})
        second: User = h.create_user(doc_org, email='second@example.com', role='admin')
        assert second.id != uuid.UUID(int=0)
        _workflow(
            client,
            doc_auth_headers,
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager Approval',
                    'approver_user_ids': [],
                }
            ],
        )
        doc_id = _draft(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )

        told = _requirement(client, doc_auth_headers, doc_id)

        assert told['approval_solvable'] is True
        assert told['undecidable_reason'] is None
        assert told['undecidable_stage'] is None

    def test_a_stage_naming_only_the_requester_is_decided_on_the_spot(
        self,
        client: TestClient,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Walked past the way the request itself walks past it: nothing parks."""
        _workflow(
            client,
            doc_auth_headers,
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Mine alone',
                    'approver_user_ids': [str(doc_user.id)],
                }
            ],
        )
        doc_id = _draft(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )

        told = _requirement(client, doc_auth_headers, doc_id)

        assert told['approval_required'] is True
        assert told['approval_solvable'] is True
