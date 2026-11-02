"""A workflow holds the documents of the people it names, and only theirs.

Approval is for the people who need it, not for everyone who files a
document: warehouse staff's receipts wait, the administrator's do not. A
workflow used to say only who decides, so whether a document waited depended
on the document alone, and the administrator who confirmed a receipt was held
like anyone else. The workflow now names whose documents it holds — everyone,
or chosen people and roles — and the one rule asks that first.
"""

import uuid
from typing import Any, cast
from uuid import uuid5

import pytest
from fastapi import status
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.public_api.roles import BUILTIN_ROLE_NAMESPACE
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.role import Role, UserRole
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.models import DocumentStatus
from app.modules.warehouse.tests.integration.test_one_definition_of_approval_required import (
    _create_in,
)

_STAGES = [{'order': 1, 'role': 'manager', 'label': 'Manager', 'approver_user_ids': []}]


def _workflow(
    client: TestClient, headers: dict[str, str], requester_scope: dict[str, Any]
) -> None:
    resp = client.post(
        '/api/v1/approvals/workflows',
        headers=headers,
        json={
            'target_type': 'document',
            'name': 'Receipts by the warehouse',
            'stages': _STAGES,
            'is_active': True,
            'expected_scope': {'holds': 'all'},
            'requester_scope': requester_scope,
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text


def _clerk(h: ModuleTestHelper, org: Organization, email: str) -> User:
    """A member who files documents: the base level plus the module's grant."""
    user = h.create_user(org, email=email, role='user')
    h.grant_permissions(user, ['warehouse:read', 'warehouse:write'])
    return user


def _granted_role(db: Session, user: User) -> uuid.UUID:
    """The custom role ``grant_permissions`` gave *user*."""
    return db.scalars(
        select(Role.id).where(Role.name == f'test_grant_{user.email.split("@")[0]}')
    ).one()


def _confirm(client: TestClient, headers: dict[str, str], doc_id: str) -> str:
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(str, resp.json()['status'])


def _requirement(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> dict[str, Any]:
    told = client.get(
        f'/api/v1/approvals/documents/{doc_id}/approval-requirement', headers=headers
    )
    assert told.status_code == status.HTTP_200_OK, told.text
    return cast(dict[str, Any], told.json())


@pytest.mark.integration
class TestAWorkflowHoldsOnlyItsRequesters:
    def test_a_named_person_parks_and_the_administrator_does_not(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        kasia = _clerk(h, doc_org, 'kasia@example.com')
        kasia_headers = h.get_auth_headers(kasia)
        _workflow(
            client,
            doc_auth_headers,
            {'everyone': False, 'user_ids': [str(kasia.id)], 'role_ids': []},
        )

        held = _create_in(
            client,
            kasia_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        own = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )

        assert _confirm(client, kasia_headers, held) == (
            DocumentStatus.PENDING_APPROVAL.value
        )
        assert _confirm(client, doc_auth_headers, own) == DocumentStatus.CONFIRMED.value
        # Nothing was raised for the administrator's document: the queue holds
        # Kasia's request alone.
        requests = client.get(
            '/api/v1/approvals/requests?status=', headers=doc_auth_headers
        ).json()['items']
        assert [r['target_id'] for r in requests] == [held]

    def test_a_role_holds_its_holders_and_follows_a_change_of_role(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        storeman = _clerk(h, doc_org, 'storeman@example.com')
        storeman_headers = h.get_auth_headers(storeman)
        role_id = _granted_role(db_session, storeman)
        _workflow(
            client,
            doc_auth_headers,
            {'everyone': False, 'user_ids': [], 'role_ids': [str(role_id)]},
        )

        first = _create_in(
            client,
            storeman_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        assert _confirm(client, storeman_headers, first) == (
            DocumentStatus.PENDING_APPROVAL.value
        )

        # Moved out of the scoped role, onto another one that still lets them
        # file documents: the next submission is not held, the open request is
        # left where it is.
        other = Role(
            name='clerk',
            permissions=['warehouse:read', 'warehouse:write'],
            is_system=False,
            organization_id=doc_org.id,
        )
        db_session.add(other)
        db_session.flush()
        db_session.execute(
            update(UserRole)
            .where(UserRole.user_id == storeman.id)
            .values(role_id=other.id)
        )
        db_session.commit()

        second = _create_in(
            client,
            storeman_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        assert _confirm(client, storeman_headers, second) == (
            DocumentStatus.CONFIRMED.value
        )
        first_now = client.get(
            f'/api/v1/warehouse/documents/{first}', headers=doc_auth_headers
        ).json()
        assert first_now['status'] == DocumentStatus.PENDING_APPROVAL.value

    def test_a_built_in_level_is_a_role_like_any_other(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        member = _clerk(h, doc_org, 'member@example.com')
        _workflow(
            client,
            doc_auth_headers,
            {
                'everyone': False,
                'user_ids': [],
                'role_ids': [str(uuid5(BUILTIN_ROLE_NAMESPACE, 'user'))],
            },
        )
        member_headers = h.get_auth_headers(member)
        doc_id = _create_in(
            client,
            member_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )

        own = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )

        assert _confirm(client, member_headers, doc_id) == (
            DocumentStatus.PENDING_APPROVAL.value
        )
        # The administrator's level is not the scoped one.
        assert _confirm(client, doc_auth_headers, own) == DocumentStatus.CONFIRMED.value

    def test_the_confirm_dialog_answers_for_the_person_asking(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        kasia = _clerk(h, doc_org, 'kasia@example.com')
        kasia_headers = h.get_auth_headers(kasia)
        _workflow(
            client,
            doc_auth_headers,
            {'everyone': False, 'user_ids': [str(kasia.id)], 'role_ids': []},
        )
        doc_id = _create_in(
            client,
            kasia_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )

        # One draft, two readers about to press the same button.
        assert _requirement(client, kasia_headers, doc_id)['approval_required'] is True
        told_admin = _requirement(client, doc_auth_headers, doc_id)
        assert told_admin['approval_required'] is False
        assert told_admin['workflow_configured'] is True
        # And the answer is what the button then does for the administrator.
        assert _confirm(client, doc_auth_headers, doc_id) == (
            DocumentStatus.CONFIRMED.value
        )

    def test_a_document_confirmed_outside_the_scope_is_executed_by_anyone(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        kasia = _clerk(h, doc_org, 'kasia@example.com')
        kasia_headers = h.get_auth_headers(kasia)
        _workflow(
            client,
            doc_auth_headers,
            {'everyone': False, 'user_ids': [str(kasia.id)], 'role_ids': []},
        )
        doc_id = _create_in(
            client,
            kasia_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        # The administrator confirms Kasia's draft: they are the one who
        # submitted it, and they are not held.
        assert _confirm(client, doc_auth_headers, doc_id) == (
            DocumentStatus.CONFIRMED.value
        )

        # Kasia, who is held, completes it. The gate asks about the person
        # who submitted the document, not the one carrying it out.
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=kasia_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text
        assert done.json()['status'] == DocumentStatus.COMPLETED.value

    def test_a_workflow_cannot_be_saved_without_saying_whose_documents_it_holds(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        missing = client.post(
            '/api/v1/approvals/workflows',
            headers=doc_auth_headers,
            json={'target_type': 'document', 'name': 'W', 'stages': _STAGES},
        )
        nobody = client.post(
            '/api/v1/approvals/workflows',
            headers=doc_auth_headers,
            json={
                'target_type': 'document',
                'name': 'W',
                'stages': _STAGES,
                'requester_scope': {'everyone': False, 'user_ids': [], 'role_ids': []},
            },
        )

        assert missing.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        # Chosen people with nobody chosen is not "nobody by accident".
        assert nobody.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
